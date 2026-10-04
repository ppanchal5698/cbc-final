#!/usr/bin/env python3
"""Register Hager PDFs already under data/pricebooks/ and queue indexing.

Unlike add_hager_pricebooks.py (copies from final_pricebooks/), this points at
files already on disk — including the compressed Price Book #18 copy — upserts
priceBooks, and enqueues index_catalog / parse_* when PARSER_URL is set.

    python apps/backend/scripts/register_pricebook_pdfs.py
    python apps/backend/scripts/register_pricebook_pdfs.py --no-index
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

from cbc.shared import storage
from cbc.shared.paths import pricebook_dir

URI = "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin&replicaSet=rs0"

HAGER_CATEGORIES = {
    "locks": 0.29,
    "door_controls": 0.3,
    "exit_devices": 0.3,
    "l_dc_e_accessories": 0.3,
    "electrified_products": 0.41,
    "auto_operators": 0.4,
    "architectural_hinges": 0.21,
    "residential_hinges": 0.375,
}

# Prefer a stable canonical filename in priceBooks; locate source by glob.
BOOKS: list[dict] = [
    {
        "patterns": [
            "hager_price_book_18.pdf",
            "Hager Price Book #18*.pdf",
            "Hager Price Book #18*.PDF",
        ],
        "file": "hager_price_book_18.pdf",
        "vendor": "hager",
        "name": "Hager Door Hardware Price Book #18",
        "effective_date": "2026-02-02",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
        "parse": True,
        "categories": None,
        "note": "List-price book. Indexed for find_pages; parsed when PARSER_URL is set.",
    },
    {
        "patterns": [
            "hager_multipliers.pdf",
            "Hager Multipliers and Special Nets*.pdf",
        ],
        "file": "hager_multipliers.pdf",
        "vendor": "hager",
        "name": "Hager multipliers and special nets",
        "effective_date": "2026-03-02",
        "kind": "multiplier_sheet",
        "divisions": ["08"],
        "index": False,
        "parse": True,
        "categories": HAGER_CATEGORIES,
        "account": "HGR 17907",
        "note": "Hager Advantage Program tiers. Special nets seeded from multipliers.md.",
    },
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_source(target: Path, patterns: list[str]) -> Path:
    for pattern in patterns:
        # Exact name first
        exact = target / pattern
        if "*" not in pattern and exact.is_file():
            return exact
        hits = sorted(target.glob(pattern), key=lambda p: p.stat().st_size, reverse=True)
        for hit in hits:
            if hit.is_file() and hit.suffix.lower() == ".pdf":
                return hit
    raise FileNotFoundError(
        f"No PDF matching {patterns!r} under {target}. Place Hager PDFs in data/pricebooks/."
    )


def ensure_canonical_files(target: Path) -> dict[str, Path]:
    """Copy/rename discovered sources to the stable filenames priceBooks expect."""
    resolved: dict[str, Path] = {}
    for entry in BOOKS:
        src = _resolve_source(target, entry["patterns"])
        dst = target / entry["file"]
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
            print(f"copied  {src.name} -> {entry['file']} ({dst.stat().st_size:,} bytes)")
        else:
            print(f"have    {entry['file']} ({dst.stat().st_size:,} bytes)")
        resolved[entry["file"]] = dst
    return resolved


def upsert_mongo(uri: str, db_name: str, target: Path) -> dict[str, str]:
    from cbc.shared.mongo_uri import reachable_uri

    client = MongoClient(reachable_uri(uri), serverSelectionTimeoutMS=5000)
    client.server_info()
    db = client[db_name]
    ids: dict[str, str] = {}

    for entry in BOOKS:
        path = target / entry["file"]
        document = {
            "vendor": entry["vendor"],
            "displayName": "Hager",
            "program": entry["name"],
            "multiplier": None,
            "categories": entry.get("categories"),
            "effective": entry["effective_date"],
            "protectedThrough": None,
            "lastReviewed": entry["effective_date"],
            "steward": "Purchasing",
            "kind": entry["kind"],
            "filename": entry["file"],
            "path": storage.relative(path),
            "bytes": path.stat().st_size,
            "account": entry.get("account"),
            "note": entry.get("note"),
            "divisions": entry.get("divisions"),
            "updatedAt": now(),
            "uploadedAt": now(),
        }
        result = db["priceBooks"].update_one(
            {"vendor": entry["vendor"], "filename": entry["file"]},
            {"$set": document, "$setOnInsert": {"partCount": 0, "createdAt": now()}},
            upsert=True,
        )
        book_id = result.upserted_id
        if book_id is None:
            book_id = db["priceBooks"].find_one(
                {"vendor": entry["vendor"], "filename": entry["file"]}
            )["_id"]
        ids[entry["file"]] = str(book_id)
        print(f"mongo   {entry['file']} -> {book_id}")

    client.close()
    return ids


async def enqueue_jobs(ids: dict[str, str], *, do_index: bool, do_parse: bool) -> None:
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings
    from cbc.modules.ops.api.jobs import enqueue

    settings.mongodb_db = os.environ.get("MONGODB_DB", "cbc_opshub")
    db_module._client = None

    for entry in BOOKS:
        book_id = ids[entry["file"]]
        filename = entry["file"]
        if do_index and entry.get("index"):
            job = await enqueue(
                "index_catalog",
                payload={"priceBookId": book_id, "filename": filename},
                actor="admin@cbc.com",
            )
            print(f"queued  index_catalog {job['_id']} for {filename}")
        if do_parse and entry.get("parse"):
            # `parse_catalog` / `parse_multiplier` went with MinerU, and enqueuing
            # a type no worker registers leaves the job queued forever. Catalog
            # search runs off the page index built by `index_catalog` above.
            print(f"skip    block parse for {filename} (catalog parsing is page-index only)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-index", action="store_true", help="Mongo + files only")
    parser.add_argument("--no-parse", action="store_true", help="Skip block parse jobs")
    parser.add_argument("--uri", default=None)
    args = parser.parse_args()

    target = pricebook_dir()
    target.mkdir(parents=True, exist_ok=True)
    ensure_canonical_files(target)

    uri = args.uri or os.environ.get("MONGODB_URI", URI)
    db_name = os.environ.get("MONGODB_DB", "cbc_opshub")
    ids = upsert_mongo(uri, db_name, target)

    if not args.no_index or not args.no_parse:
        asyncio.run(
            enqueue_jobs(
                ids,
                do_index=not args.no_index,
                do_parse=not args.no_parse,
            )
        )
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
