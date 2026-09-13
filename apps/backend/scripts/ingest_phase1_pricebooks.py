#!/usr/bin/env python3
"""Install Phase-1 top-10 vendor price books from final_pricebooks/ into Ops-Hub.

Copies PDFs and spreadsheets into pricebooks/, updates index.json, upserts Mongo
metadata, and queues index_catalog for every searchable book.

    python scripts/ingest_phase1_pricebooks.py
    python scripts/ingest_phase1_pricebooks.py --no-index   # copy + mongo only
"""
from __future__ import annotations

import argparse
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
SOURCE_ROOT = ROOT / "final_pricebooks"
TARGET = ROOT / "pricebooks"
TIERS_PATH = ROOT / "reference-library" / "multipliers" / "vendor_tiers.json"

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

PHASE1_BOOKS: list[dict] = [
    {
        "source_dir": "HAGER",
        "source": "Hager Price Book #18 - Complete - Effective 2-2-26.pdf",
        "file": "hager_price_book_18.pdf",
        "vendor": "hager",
        "name": "Hager Door Hardware Price Book #18",
        "effective_date": "2026-02-02",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
    },
    {
        "source_dir": "HAGER",
        "source": "Hager Multipliers and Special Nets - Effective 3-2-26.pdf",
        "file": "hager_multipliers.pdf",
        "vendor": "hager",
        "name": "Hager multipliers and special nets",
        "effective_date": "2026-03-02",
        "kind": "multiplier_sheet",
        "divisions": ["08"],
        "index": False,
        "categories": HAGER_CATEGORIES,
        "account": "HGR 17907",
    },
    {
        "source_dir": "ASI",
        "source": "ASI-Price-List - 1-12-26 - .375 Multiplier.pdf",
        "file": "asi_price_list.pdf",
        "vendor": "asi",
        "name": "ASI price list",
        "effective_date": "2026-01-12",
        "kind": "price_book",
        "divisions": ["10"],
        "index": True,
    },
    {
        "source_dir": "BRADLEY",
        "source": "26 price book WAD .53.pdf",
        "file": "bradley_price_book_2026.pdf",
        "vendor": "bradley",
        "name": "Bradley WAD price book 2026",
        "effective_date": "2026-01-01",
        "kind": "price_book",
        "divisions": ["10"],
        "index": True,
    },
    {
        "source_dir": "NATIONAL GUARD PRODUCTS",
        "source": "NGP Price List 6-8-2026 - .45 Multiplier.pdf",
        "file": "national_guard_price_list.pdf",
        "vendor": "national_guard",
        "name": "NGP price list",
        "effective_date": "2026-06-08",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
    },
    {
        "source_dir": "NATIONAL GUARD PRODUCTS",
        "source": "NGP Threshold Catalog.pdf",
        "file": "national_guard_threshold_catalog.pdf",
        "vendor": "national_guard",
        "name": "NGP threshold catalog",
        "effective_date": "2026-06-08",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
    },
    {
        "source_dir": "PEMKO",
        "source": "markar_and_pemko_price_book_2026.pdf",
        "file": "pemko_markar_price_book_2026.pdf",
        "vendor": "pemko",
        "name": "PEMKO / Markar price book 2026",
        "effective_date": "2026-01-01",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
    },
    {
        "source_dir": "PEMKO",
        "source": "Buying Program Account 4244636 - Effective 1-1-20.pdf",
        "file": "pemko_buying_program.pdf",
        "vendor": "pemko",
        "name": "PEMKO buying program account 4244636",
        "effective_date": "2020-01-01",
        "kind": "multiplier_sheet",
        "divisions": ["08"],
        "index": False,
    },
    {
        "source_dir": "ROCKWOOD",
        "source": "Rockwood Accessories Price Book - .55 Multiplier.pdf",
        "file": "rockwood_accessories_price_book.pdf",
        "vendor": "rockwood",
        "name": "Rockwood accessories price book",
        "effective_date": "2025-03-03",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
    },
    {
        "source_dir": "ROCKWOOD",
        "source": "Rockwood Architectural Price Book - 3-3-25.pdf",
        "file": "rockwood_architectural_price_book.pdf",
        "vendor": "rockwood",
        "name": "Rockwood architectural price book",
        "effective_date": "2025-03-03",
        "kind": "price_book",
        "divisions": ["08"],
        "index": True,
    },
    {
        "source_dir": "BOBRICK",
        "source": "Hamilton Parker 2017 Program Price Sheet Bobrick NET.xlsx",
        "file": "bobrick_hp_program_net.xlsx",
        "vendor": "bobrick",
        "name": "Bobrick HP program NET",
        "effective_date": "2017-01-01",
        "kind": "price_book",
        "divisions": ["10"],
        "index": True,
    },
    {
        "source_dir": "BOBRICK",
        "source": "Hamilton Parker 2017 Program Price Sheet Gamco.xlsx",
        "file": "gamco_hp_program_net.xlsx",
        "vendor": "gamco",
        "name": "Gamco HP program NET",
        "effective_date": "2017-01-01",
        "kind": "price_book",
        "divisions": ["10"],
        "index": True,
    },
    {
        "source_dir": "NUDO",
        "source": "MIDWEST-EAST COAST FRP 5-11-26.pdf",
        "file": "nudo_frp_pricing.pdf",
        "vendor": "nudo",
        "name": "NUDO / Midwest-East Coast FRP pricing",
        "effective_date": "2026-05-11",
        "kind": "price_book",
        "divisions": ["06"],
        "index": True,
    },
    {
        "source_dir": "WORLD DRYER",
        "source": "Copy of L-3World Dryer Pricing_9.2022_L3 - .339 MULTIPLIER.xlsx",
        "file": "world_dryer_l3_pricing.xlsx",
        "vendor": "world_dryer",
        "name": "World Dryer Level 3 pricing",
        "effective_date": "2022-09-12",
        "kind": "price_book",
        "divisions": ["10"],
        "index": True,
    },
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_tiers() -> dict[str, dict]:
    if not TIERS_PATH.exists():
        return {}
    payload = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
    return {row["key"]: row for row in payload.get("vendors", [])}


def copy_files() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for entry in PHASE1_BOOKS:
        src = SOURCE_ROOT / entry["source_dir"] / entry["source"]
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
    for entry in PHASE1_BOOKS:
        src = SOURCE_ROOT / entry["source_dir"] / entry["source"]
        by_file[entry["file"]] = {
            "vendor": entry["vendor"],
            "name": entry["name"],
            "file": entry["file"],
            "effective_date": entry["effective_date"],
            "kind": entry["kind"],
            "divisions": entry["divisions"],
            "source": f"{entry['source_dir']}/{entry['source']}",
            "size_bytes": src.stat().st_size,
        }
    payload["pricebooks"] = sorted(by_file.values(), key=lambda row: (row["vendor"], row["file"]))
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"index    {len(payload['pricebooks'])} price book(s) in index.json")


def upsert_mongo(uri: str, db_name: str) -> dict[str, str]:
    tiers = load_tiers()
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.server_info()
    db = client[db_name]
    ids: dict[str, str] = {}

    for entry in PHASE1_BOOKS:
        path = TARGET / entry["file"]
        tier = tiers.get(entry["vendor"], {})
        categories = entry.get("categories") or tier.get("categories") or None
        multiplier = tier.get("multiplier")
        if multiplier is None and categories:
            multiplier = categories.get("locks") or next(iter(categories.values()), None)

        document = {
            "vendor": entry["vendor"],
            "displayName": tier.get("name") or entry["vendor"].replace("_", " ").title(),
            "program": entry["name"],
            "multiplier": multiplier,
            "categories": categories,
            "effective": entry["effective_date"],
            "protectedThrough": None,
            "lastReviewed": tier.get("effective_date") or entry["effective_date"],
            "steward": "Purchasing",
            "kind": entry["kind"],
            "filename": entry["file"],
            "path": f"pricebooks/{entry['file']}",
            "bytes": path.stat().st_size,
            "account": entry.get("account") or tier.get("account"),
            "note": tier.get("note"),
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-index", action="store_true", help="skip index_catalog jobs")
    args = parser.parse_args()

    copy_files()
    update_index_json()
    uri = os.environ.get("MONGODB_URI", URI)
    db_name = os.environ.get("MONGODB_DB", "cbc_opshub")
    ids = upsert_mongo(uri, db_name)

    if args.no_index:
        print("\nSkipped index_catalog jobs (--no-index). Run: python -m cbc.pageindex.build --all")
        return 0

    queued = 0
    for entry in PHASE1_BOOKS:
        if not entry.get("index"):
            continue
        job_id = asyncio.run(index_price_book(ids[entry["file"]], entry["file"]))
        print(f"queued   index_catalog job {job_id} for {entry['file']}")
        queued += 1

    print(
        f"\nQueued {queued} index job(s). Watch: docker logs -f cbc-worker\n"
        "Or rebuild locally: python -m cbc.pageindex.build --all"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
