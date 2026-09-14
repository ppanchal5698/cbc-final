#!/usr/bin/env python3
"""Seed MongoDB for the CBC Ops-Hub.

    python scripts/seed_db.py            # users, price books, catalog
    python scripts/seed_db.py --reset    # drop the app collections first
    python scripts/seed_db.py --demo     # also create the Dutch Bros demo project

Price books and multiplier tiers come from the real files already in this repo
(`pricebooks/index.json`, `reference-library/multipliers/vendor_tiers.json`).

Catalog rows are marked with `seedSource` so it is always visible where a number
came from. Rows tagged `prototype sample` are illustrative figures taken from the
UI design, NOT confirmed CBC pricing - overwrite them from a real price book
before quoting anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import bcrypt
from pymongo import MongoClient

from cbc.shared.mongo_uri import reachable_uri
from cbc.shared.persistence import names

ROOT = Path(__file__).resolve().parents[1]

URI = "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin"
APP_COLLECTIONS = (
    "users",
    "projects",
    "documents",
    "lineItems",
    "quoteLines",
    "quotes",
    "proposals",
    "products",
    "priceBooks",
    "jobs",
    "auditLog",
)

USERS = [
    {
        "email": "estimator@cbc.com",
        "name": "Estimator",
        "initials": "ES",
        "role": "estimator",
        "password": "opshub",
    },
    {
        "email": "admin@cbc.com",
        "name": "Admin",
        "initials": "AD",
        "role": "admin",
        "password": "opshub",
    },
]

# Illustrative catalog rows from the UI design. Real part numbers and vendors,
# but the figures are sample data until a price book is ingested over them.
SAMPLE_PRODUCTS = [
    ("150CX18 MBLK", "Bobrick matte-black grab bar, 18 in", "Bobrick", "10 28 00", 74.20, 148.40, 0.500, "In stock",
     [("ASI", "3801-18"), ("Bradley", "812-018"), ("Gamco", "Gamco 22")]),
    ("B5806.99X36", "Peened grab bar, 36 in", "Bobrick", "10 28 00", 88.00, 176.00, 0.500, "In stock", []),
    ("B29516", "Bobrick shelf, 16 in", "Bobrick", "10 28 00", 112.00, 224.00, 0.500, "Standard lead", []),
    ("KB200-00", "Koala baby changing station, horizontal", "Koala Kare", "10 28 00", 288.00, None, None, "Standard lead", []),
    ("KB101-00", "Koala baby changing station, vertical", "Koala Kare", "10 28 00", 296.00, None, None, "Standard lead", []),
    ("0620-2436", "ASI channel-frame mirror, 24 x 36", "ASI", "10 28 00", 96.50, 257.33, 0.375, "In stock", []),
    ("10-0199-1-93", "ASI satin hand dryer", "ASI", "10 28 00", 299.25, 798.00, 0.375, "In stock", []),
    ("TA-ABS 110/120V", "Xlerator ThinAir hand dryer, 110/120V", "Excel Dryer", "10 28 00", 250.00, None, None, "In stock", []),
    ("XL-SB", "Xlerator hand dryer, brushed stainless", "Excel Dryer", "10 28 00", 369.00, None, None, "Long lead", []),
    ("ECBB1100-4.5X4.5-26D-NRP", "Hager BB hinge, 4.5 x 4.5, US26D, NRP", "Hager", "08 71 00", 34.60, 119.30, 0.290, "In stock", []),
    ("AB700-4.5X4.5-US26D", "Hager concealed BB hinge", "Hager", "08 71 00", 41.50, 143.10, 0.290, "In stock", []),
    ("5100-ALU", "Hager 5100 door closer, aluminium", "Hager", "08 71 00", 124.00, 365.80, 0.300, "In stock", []),
    ("NGP-896", "National Guard 896 threshold", "National Guard", "08 71 00", 46.50, 103.33, 0.450, "In stock", []),
    ("S861307010", "3-0 x 7-0 HM door, cylindrical prep, galvanised", "CBC hollow metal", "08 11 00", 412.00, None, None, "Standard lead", []),
    ("KNOCKDOWN5625", "Knock-down frame, 5-5/8 in wall, 16ga", "CBC hollow metal", "08 11 00", 212.00, None, None, "Standard lead", []),
    ("WELD575", "Welded frame, 5-3/4 in wall", "CBC hollow metal", "08 11 00", 268.00, None, None, "Custom fabrication", []),
    ("WD-PS-MAPLE-20", "Wood door, plain-sliced white maple, 20-minute", "Graham", "08 14 00", 521.00, None, None, "Long lead", []),
    ("S861306830", "HM door pair, mortise prep, 5-7/8 knock-down frame", "CBC hollow metal", "08 11 00", 438.50, None, None, "Standard lead", []),
    ("S861306880", "HM door, SVR reinforced prep", "CBC hollow metal", "08 11 00", 455.00, None, None, "Standard lead", []),
    ("FRP-NUDO-4X8", "NUDO FRP wall panel, 4 x 8", "NUDO", "06 64 00", 38.00, None, None, "In stock", []),
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def seed_users(db) -> int:
    for user in USERS:
        db["users"].update_one(
            {"email": user["email"]},
            {
                "$set": {
                    "email": user["email"],
                    "name": user["name"],
                    "initials": user["initials"],
                    "role": user["role"],
                    "passwordHash": bcrypt.hashpw(
                        user["password"].encode(), bcrypt.gensalt()
                    ).decode(),
                    "updatedAt": now(),
                },
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
    return len(USERS)


def seed_price_books(db) -> int:
    """Build price-book rows from the real index plus the real multiplier tiers."""
    index_path = ROOT / "pricebooks" / "index.json"
    tiers_path = ROOT / "reference-library" / "multipliers" / "vendor_tiers.json"
    if not index_path.exists():
        print("  ! pricebooks/index.json missing - skipping price books")
        return 0

    books = json.loads(index_path.read_text(encoding="utf-8")).get("pricebooks", [])
    tiers = {}
    if tiers_path.exists():
        payload = json.loads(tiers_path.read_text(encoding="utf-8"))
        tiers = {v["key"]: v for v in payload.get("vendors", [])}

    count = 0
    for book in books:
        vendor_key = book.get("vendor", "")
        tier = tiers.get(vendor_key, {})
        categories = tier.get("categories") or {}
        multiplier = tier.get("multiplier")
        # Hager prices by product category; surface the locks tier as headline.
        if multiplier is None and categories:
            multiplier = categories.get("locks") or next(iter(categories.values()), None)

        db["priceBooks"].update_one(
            {"vendor": vendor_key, "filename": book["file"]},
            {
                "$set": {
                    "vendor": vendor_key,
                    "displayName": tier.get("name") or vendor_key.replace("_", " ").title(),
                    "program": book.get("name"),
                    "multiplier": multiplier,
                    "categories": categories or None,
                    "effective": book.get("effective_date"),
                    "protectedThrough": None,
                    "lastReviewed": tier.get("effective_date"),
                    "steward": "Purchasing" if multiplier else None,
                    "kind": book.get("kind"),
                    "filename": book["file"],
                    "path": f"pricebooks/{book['file']}",
                    "account": tier.get("account"),
                    "note": tier.get("note"),
                    "updatedAt": now(),
                },
                "$setOnInsert": {"partCount": 0, "createdAt": now()},
            },
            upsert=True,
        )
        count += 1
    return count


def seed_products(db) -> int:
    books = {b["vendor"]: b for b in db["priceBooks"].find()}
    vendor_for = {
        "Bobrick": "bobrick",
        "Koala Kare": None,
        "ASI": "asi",
        "Excel Dryer": None,
        "Hager": "hager",
        "National Guard": "national_guard",
        "CBC hollow metal": None,
        "Graham": None,
        "NUDO": "nudo",
    }

    count = 0
    for part, desc, mfr, div, cost, list_price, mult, avail, xref in SAMPLE_PRODUCTS:
        book = books.get(vendor_for.get(mfr) or "")
        db[names.CATALOG_ITEMS].update_one(
            {"part": part},
            {
                "$set": {
                    "part": part,
                    "description": desc,
                    "manufacturer": mfr,
                    "division": div,
                    "cost": cost,
                    "listPrice": list_price,
                    "multiplier": mult,
                    "availability": avail,
                    "priceBookId": book["_id"] if book else None,
                    "priceBook": book.get("program") if book else None,
                    "xref": [{"manufacturer": m, "part": p} for m, p in xref],
                    "seedSource": "prototype sample",
                    "updatedAt": now(),
                    "updatedBy": "seed",
                },
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
        count += 1

    for book in books.values():
        db["priceBooks"].update_one(
            {"_id": book["_id"]},
            {"$set": {"partCount": db[names.CATALOG_ITEMS].count_documents({"priceBookId": book["_id"]})}},
        )
    return count


def seed_demo_project(db) -> str | None:
    """Create the Dutch Bros bid from the fixture already in the repo."""
    from cbc.shared import storage

    fixture = ROOT / "tests" / "fixtures" / "pdfs" / "1_Architectural.pdf"
    if not fixture.exists():
        print("  ! tests/fixtures/pdfs/1_Architectural.pdf missing - skipping demo project")
        return None

    code = "CBC-260143"
    slug = "dutch_bros_macarthur_2026"
    db[names.BID_REQUESTS].update_one(
        {"code": code},
        {
            "$set": {
                "code": code,
                "slug": slug,
                "name": "Dutch Bros Coffee - MacArthur Dr",
                "brand": "Dutch Bros Coffee",
                "jobName": "DUTCH BROS #LA0701",
                "projectNumber": "LA0701",
                "location": "1804 MacArthur Drive, Alexandria, LA",
                "state": "LA",
                "architect": "Coralic LLC",
                "gc": None,
                "initiator": None,
                "stage": "intake",
                "progress": 0,
                "updatedAt": now(),
            },
            "$setOnInsert": {"createdAt": now()},
        },
        upsert=True,
    )
    project = db[names.BID_REQUESTS].find_one({"code": code})

    storage.scaffold(slug)
    target = storage.raw_dir(slug) / fixture.name
    if not target.exists():
        target.write_bytes(fixture.read_bytes())

    if not db["documents"].find_one({"projectId": project["_id"], "filename": fixture.name}):
        import fitz

        doc = fitz.open(target)
        pages = doc.page_count
        doc.close()
        db["documents"].insert_one(
            {
                "projectId": project["_id"],
                "filename": fixture.name,
                "kind": "plan",
                "pages": pages,
                "bytes": target.stat().st_size,
                "path": f"projects/{slug}/uploads/raw/{fixture.name}",
                "state": "received",
                "uploadedAt": now(),
                "uploadedBy": "seed",
            }
        )
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop app collections first")
    parser.add_argument("--demo", action="store_true", help="also create the Dutch Bros project")
    parser.add_argument("--uri", default=None)
    args = parser.parse_args()

    import os

    client = MongoClient(reachable_uri(args.uri or os.environ.get("MONGODB_URI", URI)), serverSelectionTimeoutMS=5000)
    db = client[os.environ.get("MONGODB_DB", "cbc_opshub")]
    client.server_info()

    if args.reset:
        for name in APP_COLLECTIONS:
            db[name].drop()
        print("dropped app collections")

    print(f"users        {seed_users(db):>4}")
    print(f"price books  {seed_price_books(db):>4}")
    print(f"products     {seed_products(db):>4}")

    if args.demo:
        code = seed_demo_project(db)
        print(f"demo project {code or 'skipped':>4}")

    print("\nSign in with estimator@cbc.com or admin@cbc.com / opshub")
    print(
        "Catalog rows tagged seedSource='prototype sample' carry illustrative "
        "figures - replace them by ingesting a real price book."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
