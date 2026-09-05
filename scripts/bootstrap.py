#!/usr/bin/env python3
"""Idempotent first-run bootstrap for Docker and fresh installs.

Runs automatically from docker/entrypoint.sh when AUTO_BOOTSTRAP is not 0.

  * Seeds users, price books, and sample catalog rows when the users collection
    is empty.
  * Builds the MongoDB page index when no catalog has been indexed yet.

Safe to run on every start: each step no-ops when already satisfied.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _may_seed_accounts() -> bool:
    """Only seed the published dev accounts where they are meant to exist.

    seed_users creates admin@cbc.com with the password `opshub`, which is in this
    repository. docker/entrypoint.sh runs this file whenever AUTO_BOOTSTRAP is not
    0 and compose leaves it unset, so the first start of any deployment against an
    empty database created a known-password admin - regardless of APP_ENV.
    config._assert_production_secrets does not cover it: it gates secrets, not
    seeded accounts, and it runs after this.

    Unset does not mean development here. An environment that has not said what it
    is does not get credentials published on the internet.
    """
    declared = (os.environ.get("APP_ENV") or "").strip().lower()
    if declared in ("development", "dev", "local", "test"):
        return True
    print(
        f"[bootstrap] APP_ENV={declared or '(unset)'} - skipping the seed accounts. "
        "Create the first user deliberately, or set APP_ENV=development locally."
    )
    return False


def main() -> int:
    from pymongo import MongoClient

    uri = os.environ.get(
        "MONGODB_URI",
        "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin",
    )
    db_name = os.environ.get("MONGODB_DB", "cbc_opshub")

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.server_info()
        db = client[db_name]
    except Exception as exc:
        print(f"[bootstrap] MongoDB not ready: {exc}")
        return 0  # entrypoint must not block container start

    if db["users"].estimated_document_count() == 0 and _may_seed_accounts():
        from scripts.seed_db import seed_price_books, seed_products, seed_users

        print("[bootstrap] empty database — seeding users, price books, and catalog")
        seed_users(db)
        seed_price_books(db)
        seed_products(db)
        print("[bootstrap] sign in with estimator@cbc.com or admin@cbc.com / opshub")
    elif db["users"].estimated_document_count():
        print("[bootstrap] users already present — skipping database seed")
    # The empty-database-but-not-permitted case has already printed its reason,
    # and saying "users already present" there would contradict it.

    # The page index lives in MongoDB, so ask MongoDB whether it is there. This
    # used to test for `.index/catalog.sqlite3` - the SQLite index PageIndex
    # replaced - which no longer exists and never will, so the guard was always
    # true and build_all() walked every catalog on every single start while
    # printing a path it does not write.
    from cbc.pageindex.store import COLLECTION as PAGE_INDEX

    indexed = db[PAGE_INDEX].count_documents({})
    if indexed:
        print(f"[bootstrap] page index already built ({indexed} catalogs)")
    else:
        pricebook_dir = Path(os.environ.get("PRICEBOOK_DIR", ROOT / "pricebooks"))
        if not pricebook_dir.is_absolute():
            pricebook_dir = (ROOT / pricebook_dir).resolve()
        if pricebook_dir.is_dir():
            print(f"[bootstrap] building the page index from {pricebook_dir}")
            from cbc.pageindex.build import build_all

            import asyncio
            asyncio.run(build_all())
            print(f"[bootstrap] page index ready ({db[PAGE_INDEX].count_documents({})} catalogs)")
        else:
            print(f"[bootstrap] pricebook dir missing ({pricebook_dir}) — index not built")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
