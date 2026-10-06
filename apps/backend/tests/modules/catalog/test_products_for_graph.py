"""What the catalog hands the memory graph: every field the graph links on."""
from __future__ import annotations

import asyncio

import pytest

from cbc.modules.catalog.api import products
from cbc.shared.persistence import names
from tests.shared import mongo_client, require_mongo

TEST_DB = "cbc_opshub_test_products_for_graph"


@pytest.fixture()
def db():
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings

    raw = mongo_client()
    require_mongo(raw)
    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    db_module._client = None
    raw.drop_database(TEST_DB)
    try:
        yield raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


def test_a_catalog_row_reaches_the_graph_with_its_division_category_and_multiplier(db):
    db[names.CATALOG_ITEMS].insert_one({
        "part": "1547A", "manufacturer": "Pemko", "division": "08 71 00", "category": "continuous_hinges",
        "listPrice": 26.92, "cost": 12.92, "multiplier": 0.48, "priceBasis": "list_x_multiplier",
    })

    async def collect():
        return [row async for row in products.iter_items()]

    [row] = run(collect())
    for field in ("part", "manufacturer", "division", "category", "listPrice", "cost", "multiplier", "priceBasis"):
        assert field in row, field
    assert row["multiplier"] == 0.48
