"""Startup indexes take over what an earlier app built on the same keys.

`docker compose up` on the dev database stopped twice at a named index whose keys
already carried another name: authAttempts' TTL `at_1` against `attempt_ttl`, and
catalogItems' text index against `product_search` (a collection has one text index).
"""
from __future__ import annotations

import asyncio

import pytest

from tests.shared import mongo_client

TEST_DB = "cbc_opshub_test_legacy_indexes"


@pytest.fixture()
def database():
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")
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


def test_ops_and_catalog_indexes_replace_the_legacy_names(database) -> None:
    from cbc.modules import catalog, ops
    from cbc.shared import mongo as db_module
    from cbc.shared.persistence import names

    database[names.AUTH_ATTEMPTS].create_index([("at", 1)], expireAfterSeconds=300)  # auto-named at_1
    database[names.CATALOG_ITEMS].create_index([("sku", "text"), ("description", "text")])

    async def startup() -> None:
        db_module._client = None
        await ops.ensure_indexes()
        await catalog.ensure_indexes()

    asyncio.run(startup())

    attempts = database[names.AUTH_ATTEMPTS].index_information()
    assert "attempt_ttl" in attempts and "at_1" not in attempts
    assert "product_search" in database[names.CATALOG_ITEMS].index_information()
