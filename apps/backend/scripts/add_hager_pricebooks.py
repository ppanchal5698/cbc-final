#!/usr/bin/env python3
"""Install the two Hager sheets from final_pricebooks/ into Ops-Hub.

After reading both PDFs:
  * Price Book #18 (744 pp) — full list-price catalog → indexed for search
  * Multipliers & Special Nets (4 pp) — category tiers + net overrides → metadata only

    python scripts/add_hager_pricebooks.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]

URI = "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin"

SOURCE = ROOT / "final_pricebooks" / "HAGER"
TARGET = ROOT / "pricebooks"

FILES = (
    {
        "source": "Hager Price Book #18 - Complete - Effective 2-2-26.pdf",
        "file": "hager_price_book_18.pdf",
        "vendor": "hager",
        "name": "Hager Door Hardware Price Book #18",
        "effective_date": "2026-02-02",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
        "multiplier": None,
        "categories": None,
        "note": "744-page list-price book. Priced by category multiplier from the companion sheet.",
    },
    {
        "source": "Hager Multipliers and Special Nets - Effective 3-2-26.pdf",
        "file": "hager_multipliers.pdf",
        "vendor": "hager",
        "name": "Hager multipliers and special nets",
        "effective_date": "2026-03-02",
        "kind": "multiplier_sheet",
        "divisions": ["08"],
        "index": False,
        "multiplier": None,
        "categories": {
            "locks": 0.29,
            "door_controls": 0.3,
            "exit_devices": 0.3,
            "l_dc_e_accessories": 0.3,
            "electrified_products": 0.41,
            "auto_operators": 0.4,
            "architectural_hinges": 0.21,
            "residential_hinges": 0.375,
        },
        "account": "HGR 17907",
        "note": "Hager Advantage Program tiers for account HGR 17907. Special net items on pp 2–4.",
    },
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def copy_files() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for entry in FILES:
        src = SOURCE / entry["source"]
        dst = TARGET / entry["file"]
        if not src.exists():
            raise FileNotFoundError(src)
        shutil.copy2(src, dst)
        print(f"copied  {entry['file']} ({dst.stat().st_size:,} bytes)")


def update_index_json() -> None:
    index_path = TARGET / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {
        "description": "Inventory of CBC vendor price books. Read-only during a pipeline run.",
        "generated_from": "final_pricebooks/",
        "refresh_cadence": "UNDEFINED - see .claude/rules/data-stewardship.md (NFR-10, OPEN)",
        "pricebooks": [],
    }
    by_file = {row["file"]: row for row in payload.get("pricebooks", [])}
    for entry in FILES:
        src = SOURCE / entry["source"]
        by_file[entry["file"]] = {
            "vendor": entry["vendor"],
            "name": entry["name"],
            "file": entry["file"],
            "effective_date": entry["effective_date"],
            "kind": entry["kind"],
            "divisions": entry["divisions"],
            "source": f"HAGER/{entry['source']}",
            "size_bytes": src.stat().st_size,
        }
    payload["pricebooks"] = list(by_file.values())
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"index    {len(payload['pricebooks'])} price book(s) in index.json")


def upsert_mongo(uri: str, db_name: str) -> dict[str, str]:
    from bson import ObjectId

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.server_info()
    db = client[db_name]
    ids: dict[str, str] = {}

    for entry in FILES:
        path = TARGET / entry["file"]
        document = {
            "vendor": entry["vendor"],
            "displayName": "Hager",
            "program": entry["name"],
            "multiplier": entry["multiplier"],
            "categories": entry.get("categories"),
            "effective": entry["effective_date"],
            "protectedThrough": None,
            "lastReviewed": entry["effective_date"],
            "steward": "Purchasing",
            "kind": entry["kind"],
            "filename": entry["file"],
            "path": f"pricebooks/{entry['file']}",
            "bytes": path.stat().st_size,
            "account": entry.get("account"),
            "note": entry.get("note"),
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
        print(f"mongo    {entry['file']} -> {book_id}")

    client.close()
    return ids


async def index_price_book(book_id: str, filename: str) -> str:
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings
    from cbc.modules.ops.api.jobs import enqueue

    settings.mongodb_db = os.environ.get("MONGODB_DB", "cbc_opshub")
    db_module._client = None
    job = await enqueue(
        "index_catalog",
        payload={"priceBookId": book_id, "filename": filename},
        actor="admin@cbc.com",
    )
    return str(job["_id"])


def main() -> int:
    copy_files()
    update_index_json()
    uri = os.environ.get("MONGODB_URI", URI)
    db_name = os.environ.get("MONGODB_DB", "cbc_opshub")
    ids = upsert_mongo(uri, db_name)

    price_book = next(e for e in FILES if e["index"])
    job_id = asyncio.run(index_price_book(ids[price_book["file"]], price_book["file"]))
    print(f"queued   index_catalog job {job_id} for {price_book['file']}")
    print(
        "\nThe worker will index ~744 pages into the catalog search index.\n"
        "Watch progress: docker logs -f cbc-worker"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
