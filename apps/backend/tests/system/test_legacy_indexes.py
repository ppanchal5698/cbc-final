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


def test_the_legacy_text_index_is_named_in_either_servers_words() -> None:
    """MongoDB and Azure DocumentDB report the text-index clash differently.

    CI runs MongoDB only, so the DocumentDB wording is pinned here too - it is
    what stopped the API booting on DocumentDB with a legacy text index.
    """
    from cbc.shared.mongo import existing_index_name

    mongo = (
        "An equivalent index already exists with a different name and options. "
        'Requested index: { v: 2, key: { _fts: "text", _ftsx: 1 }, name: "product_search" }, '
        'existing index: { v: 2, key: { _fts: "text", _ftsx: 1 }, name: "sku_text", '
        'weights: { description: 1, sku: 1 }, default_language: "english" }'
    )
    documentdb = (
        'Expected exactly one text index. Requested index: { "v" : 2, "key" : { "part" : '
        '"text" }, "name" : "product_search" }, existing index: { "v" : 2, "key" : { '
        '"partname" : "text", "description" : "text" }, "name" : "sku_text_description_text" }'
    )
    assert existing_index_name(mongo) == "sku_text"
    assert existing_index_name(documentdb) == "sku_text_description_text"
    assert existing_index_name("no index named here") is None


def test_a_managed_cluster_derives_no_readonly_uri(monkeypatch) -> None:
    """A TLS or SRV cluster's read-only user is its owner's to provision.

    A derived URI would drop the TLS options and name a user that is not there.
    A plain local URI still derives one, and an explicit one always wins.
    """
    from cbc.shared import mongo
    from cbc.shared.config import settings

    monkeypatch.delenv("MONGODB_READONLY_URI", raising=False)
    for uri in (
        "mongodb://cbc:pw@localhost:10260/?tls=true&tlsAllowInvalidCertificates=true",
        "mongodb+srv://cbc:pw@cbc.global.mongocluster.cosmos.azure.com/?tls=true",
    ):
        monkeypatch.setattr(settings, "mongodb_uri", uri)
        assert mongo.readonly_uri() is None
        assert asyncio.run(mongo.ensure_readonly_user()) is False

    monkeypatch.setattr(settings, "mongodb_uri", "mongodb://cbc:pw@mongo:27017/?authSource=admin")
    assert mongo.readonly_uri().startswith(f"mongodb://{mongo.READONLY_USER}:")

    monkeypatch.setenv("MONGODB_READONLY_URI", "mongodb://ro:pw@db:10260/?tls=true")
    assert mongo.readonly_uri() == "mongodb://ro:pw@db:10260/?tls=true"
