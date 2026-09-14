"""A fresh database's bootstrap seed runs to the end.

seed_products used `names` without importing it, so the first start of every
empty stack seeded the two users and then raised NameError: no sample catalog,
and the entrypoint reported it as "MongoDB may still be starting".
"""
from __future__ import annotations

import pytest

from tests.shared import mongo_client

TEST_DB = "cbc_opshub_test_seed_db"


def test_the_bootstrap_seed_runs_to_the_end() -> None:
    from cbc.shared.persistence import names
    from scripts.seed_db import SAMPLE_PRODUCTS, seed_price_books, seed_products, seed_users

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")
    raw.drop_database(TEST_DB)
    try:
        db = raw[TEST_DB]
        assert seed_users(db) == 2
        seed_price_books(db)
        assert seed_products(db) == len(SAMPLE_PRODUCTS)
        assert db[names.CATALOG_ITEMS].count_documents({"seedSource": "prototype sample"}) == len(SAMPLE_PRODUCTS)
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
