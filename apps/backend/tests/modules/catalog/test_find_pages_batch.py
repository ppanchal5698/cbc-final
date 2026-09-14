"""find_pages loads the catalogs it ranks in one round trip."""
from __future__ import annotations

import asyncio

from cbc.modules.catalog.api.pageindex import query, store


def test_find_pages_fetches_every_catalog_in_one_query(monkeypatch) -> None:
    headers = [{"_id": f"catalog_{n}", "vendor": "hager", "builtAt": "b1"} for n in range(6)]
    calls = {"many": 0, "one": 0}

    async def list_catalogs(vendor=None):
        return headers

    async def get_many(catalog_ids):
        calls["many"] += 1
        assert catalog_ids == [header["_id"] for header in headers]
        return []

    async def get(catalog_id):
        calls["one"] += 1

    monkeypatch.setattr(store, "list_catalogs", list_catalogs)
    monkeypatch.setattr(store, "get_many", get_many)
    monkeypatch.setattr(store, "get", get)
    query._api_find_cache.clear()

    asyncio.run(query.find_pages("butt hinge", vendor="hager"))

    assert calls == {"many": 1, "one": 0}
