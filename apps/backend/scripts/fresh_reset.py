#!/usr/bin/env python3
"""Wipe Ops-Hub to a clean slate — dev sign-in accounts only.

Removes all bids, price books, catalog rows, jobs, and on-disk project workspaces.
Resets pricebooks/ and the SQLite catalog index. Re-seeds only the two local
developer accounts (estimator@cbc.com, admin@cbc.com).

    python scripts/fresh_reset.py
    python scripts/fresh_reset.py --yes   # skip confirmation prompt
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]

URI = "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin"

COLLECTIONS = (
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
    "calls",
    "estimateVersions",
    "counters",
    "settings",
    # The page index. Absent here, a "fresh" install kept every indexed catalog
    # while reset_pricebooks() deleted the very PDFs those pages point at.
    "pageIndex",
)

PRICEBOOK_KEEP = frozenset({"index.json", "README.md"})


def reset_mongo(uri: str, db_name: str) -> None:
    from scripts.seed_db import seed_users

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.server_info()
    db = client[db_name]

    for name in COLLECTIONS:
        db[name].drop()

    count = seed_users(db)
    client.close()
    print(f"mongodb      dropped {len(COLLECTIONS)} collections, seeded {count} users")


def reset_pricebooks(pricebook_dir: Path) -> None:
    removed = 0
    for path in pricebook_dir.iterdir():
        if not path.is_file() or path.name in PRICEBOOK_KEEP:
            continue
        path.unlink(missing_ok=True)
        removed += 1

    index = {
        "description": "Inventory of CBC vendor price books. Read-only during a pipeline run.",
        "generated_from": "final_pricebooks/",
        "refresh_cadence": "UNDEFINED - see .claude/rules/data-stewardship.md (NFR-10, OPEN)",
        "pricebooks": [],
    }
    (pricebook_dir / "index.json").write_text(
        json.dumps(index, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"pricebooks   removed {removed} files, index.json cleared")


def reset_projects(storage_root: Path) -> None:
    removed = 0
    for path in storage_root.iterdir():
        if path.name == ".gitkeep":
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    print(f"projects     removed {removed} workspace(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    parser.add_argument("--uri", default=None)
    parser.add_argument("--skip-docker", action="store_true", help="only reset Mongo and local folders")
    args = parser.parse_args()

    if not args.yes:
        print(
            "This removes ALL bids, price books, catalog data, and project files.\n"
            "Only estimator@cbc.com and admin@cbc.com will remain.\n"
        )
        if input("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return 1

    uri = args.uri or os.environ.get("MONGODB_URI", URI)
    db_name = os.environ.get("MONGODB_DB", "cbc_opshub")

    reset_mongo(uri, db_name)
    reset_pricebooks(ROOT / "pricebooks")
    reset_projects(ROOT / "projects")

    # No catalog step here any more. The page index is a Mongo collection, so
    # reset_mongo() above already dropped it - there is no `catalog_index`
    # volume left in docker-compose.yml and no SQLite file to unlink. The worker
    # rebuilds the index from pricebooks/ on its next start.
    print("catalog      page index dropped with the other collections")

    print("\nFresh install ready. Sign in with estimator@cbc.com or admin@cbc.com / opshub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
