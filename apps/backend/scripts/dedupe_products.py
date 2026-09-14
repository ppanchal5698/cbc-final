#!/usr/bin/env python3
"""Merge catalog rows that share a manufacturer and part, so the identity index can be built.

    python scripts/dedupe_products.py            # report what would change
    python scripts/dedupe_products.py --apply    # merge

Catalog's unique (manufacturer, part) index cannot be built while two rows share
that pair, and startup logs an error that names this script. For each such group
the most recently updated row is kept. Quote lines and openings that point at a
removed row by productId are re-pointed at the kept one first, so nothing is left
referring to a part that no longer exists. Without --apply nothing changes.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from pymongo import MongoClient

from cbc.shared.mongo_uri import reachable_uri
from cbc.shared.persistence import names

URI = "mongodb://cbc:cbc_local_dev@localhost:27017/cbc_opshub?authSource=admin"
REFERRERS = (names.ESTIMATE_LINES, names.OPENINGS)


def duplicate_groups(db) -> list[dict[str, Any]]:
    """Each (manufacturer, part) held by more than one row, newest row first."""
    return list(db[names.CATALOG_ITEMS].aggregate([
        {"$sort": {"updatedAt": -1, "_id": -1}},
        {"$group": {
            "_id": {"manufacturer": "$manufacturer", "part": "$part"},
            "ids": {"$push": "$_id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]))


def merge(db, group: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    keep, *drop = group["ids"]
    references = 0
    for collection in REFERRERS:
        query = {"productId": {"$in": [*drop, *(str(old) for old in drop)]}}
        if apply:
            references += db[collection].update_many(query, {"$set": {"productId": str(keep)}}).modified_count
        else:
            references += db[collection].count_documents(query)
    if apply:
        db[names.CATALOG_ITEMS].delete_many({"_id": {"$in": drop}})
    return {"keep": keep, "drop": drop, "references": references}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="merge; without it nothing changes")
    parser.add_argument("--uri", default=None)
    args = parser.parse_args()

    client = MongoClient(reachable_uri(args.uri or os.environ.get("MONGODB_URI", URI)), serverSelectionTimeoutMS=5000)
    db = client[os.environ.get("MONGODB_DB", "cbc_opshub")]
    groups = duplicate_groups(db)
    if not groups:
        print("no two catalog rows share a manufacturer and part - the identity index can be built")
        return 0
    for group in groups:
        result = merge(db, group, apply=args.apply)
        key = group["_id"]
        print(
            f"{'merged' if args.apply else 'would merge'} {len(result['drop'])} row(s) of "
            f"{key.get('manufacturer')!r} {key.get('part')!r} into {result['keep']}; "
            f"{result['references']} reference(s) {'re-pointed' if args.apply else 'to re-point'}"
        )
    print("\nrestart the API to build the index" if args.apply else "\nnothing changed - run again with --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
