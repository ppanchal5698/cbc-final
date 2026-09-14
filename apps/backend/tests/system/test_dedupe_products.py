"""The script startup's error message names exists, and merges without orphaning references."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from bson import ObjectId

from tests.shared import mongo_client

TEST_DB = "cbc_opshub_test_dedupe_products"


def test_duplicates_merge_into_the_newest_row_and_references_follow() -> None:
    from cbc.shared.persistence import names
    from scripts.dedupe_products import duplicate_groups, merge

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")
    raw.drop_database(TEST_DB)
    try:
        db = raw[TEST_DB]
        old, newer, newest, other = (ObjectId() for _ in range(4))
        stamp = lambda day: datetime(2026, 9, day, tzinfo=timezone.utc)  # noqa: E731
        db[names.CATALOG_ITEMS].insert_many([
            {"_id": old, "part": "DOOR-A", "updatedAt": stamp(1)},
            {"_id": newer, "part": "DOOR-A", "updatedAt": stamp(2)},
            {"_id": newest, "part": "DOOR-A", "updatedAt": stamp(3)},
            {"_id": other, "part": "DOOR-A", "manufacturer": "Hager", "updatedAt": stamp(1)},
        ])
        db[names.ESTIMATE_LINES].insert_one({"productId": str(old)})
        db[names.OPENINGS].insert_one({"productId": str(newer)})

        (group,) = duplicate_groups(db)
        assert merge(db, group, apply=False)["references"] == 2
        assert db[names.CATALOG_ITEMS].count_documents({}) == 4, "a dry run changes nothing"

        result = merge(db, group, apply=True)
        assert result["keep"] == newest and result["references"] == 2
        assert sorted(row["_id"] for row in db[names.CATALOG_ITEMS].find()) == sorted([newest, other])
        assert db[names.ESTIMATE_LINES].find_one()["productId"] == str(newest)
        assert db[names.OPENINGS].find_one()["productId"] == str(newest)
        assert duplicate_groups(db) == []
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
