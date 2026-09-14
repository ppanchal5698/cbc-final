"""match_and_price's post-pass judges a whole bid in two round trips, not two a door."""
from __future__ import annotations

import asyncio

import pytest

from cbc.modules.quoting.features import MatchAndPrice
from tests.shared import mongo_client


def test_the_post_pass_makes_one_catalog_query_and_one_bulk_write(monkeypatch) -> None:
    openings = [{"_id": n, "mark": f"{n:02d}", "fireRating": "20"} for n in range(1, 51)]
    lines = [{"mark": f"{n:02d}", "part": "3400"} for n in range(1, 51)]
    calls = {"by_parts": 0, "by_part": 0, "bulk": 0, "single": 0}

    async def list_openings(project_id, limit=None):
        return openings

    async def list_lines(project_id, limit=None):
        return lines

    async def by_parts(parts, limit_each=20):
        calls["by_parts"] += 1
        assert sorted(set(parts)) == ["3400"]
        return {"3400": [{"_id": "p1", "part": "3400", "fireRating": "20"}]}

    async def by_part(*args, **kwargs):
        calls["by_part"] += 1
        return []

    async def update_fields_many(updates):
        calls["bulk"] += 1
        assert [opening_id for opening_id, _ in updates] == list(range(1, 51))

    async def update_fields(*args, **kwargs):
        calls["single"] += 1

    monkeypatch.setattr(MatchAndPrice.extraction_openings, "list_for_project", list_openings)
    monkeypatch.setattr(MatchAndPrice.quoting_lines, "list_for_project", list_lines)
    monkeypatch.setattr(MatchAndPrice.catalog_products, "by_parts", by_parts)
    monkeypatch.setattr(MatchAndPrice.catalog_products, "by_part", by_part)
    monkeypatch.setattr(MatchAndPrice.extraction_openings, "update_fields_many", update_fields_many)
    monkeypatch.setattr(MatchAndPrice.extraction_openings, "update_fields", update_fields)

    result = asyncio.run(MatchAndPrice.apply_to_project({"_id": "bid"}))

    assert result["openings"] == 50
    assert calls == {"by_parts": 1, "by_part": 0, "bulk": 1, "single": 0}


def test_by_parts_keeps_each_parts_cap() -> None:
    from cbc.modules.catalog.api import products
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings
    from cbc.shared.persistence import names

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")
    database, previous = "cbc_opshub_test_by_parts", settings.mongodb_db
    raw.drop_database(database)
    settings.mongodb_db, db_module._client = database, None
    try:
        raw[database][names.CATALOG_ITEMS].insert_many(
            [{"part": "A", "manufacturer": f"m{n}"} for n in range(25)] + [{"part": "B", "manufacturer": "m"}]
        )

        async def fetch():
            db_module._client = None
            return await products.by_parts(["A", "B", "C", "A", ""], limit_each=20)

        found = asyncio.run(fetch())
        assert {part: len(rows) for part, rows in found.items()} == {"A": 20, "B": 1, "C": 0}
    finally:
        settings.mongodb_db, db_module._client = previous, None
        raw.drop_database(database)
        raw.close()
