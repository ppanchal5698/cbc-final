"""Price-book staleness decoration."""

from __future__ import annotations

import pytest

from cbc.modules.catalog.infrastructure import price_book_view as view
from cbc.modules.ops.api import freshness


@pytest.fixture(autouse=True)
def _fresh_bands(monkeypatch):
    """Pin the bands: these tests are about the decoration rule, not the settings.

    `catalog_stale_days` is read through a process-global cache with a TTL, and
    on a miss it reads whichever database the previous test file left configured
    - `test_platform` PUTs `/api/settings/freshness` into its own. So the answer
    here depended on suite order. Clearing the cache was not enough, because the
    reload still went somewhere unpredictable; supplying the bands removes the
    dependency entirely.
    """
    freshness.clear_cache()

    async def fixed_bands():
        return freshness.DEFAULTS

    monkeypatch.setattr(freshness, "load", fixed_bands)
    yield
    freshness.clear_cache()


@pytest.mark.asyncio
async def test_production_staleness_uses_effective_only(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PRICEBOOK_DEV_FRESHNESS", raising=False)

    book = {
        "_id": "abc",
        "vendor": "rockwood",
        "effective": "2022-08-15",
        "lastReviewed": "2026-09-16",
    }
    decorated = await view.decorate(book)

    assert decorated["stale"] is True
    assert decorated["staleReferenceField"] == "effective"
    assert decorated["devFreshnessControls"] is False


@pytest.mark.asyncio
async def test_dev_staleness_prefers_last_reviewed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("PRICEBOOK_DEV_FRESHNESS", raising=False)

    book = {
        "_id": "abc",
        "vendor": "rockwood",
        "effective": "2022-08-15",
        "lastReviewed": "2026-09-16",
    }
    decorated = await view.decorate(book)

    assert decorated["stale"] is False
    assert decorated["staleReferenceField"] == "lastReviewed"
    assert decorated["devFreshnessControls"] is True


@pytest.mark.asyncio
async def test_dev_staleness_can_be_forced_stale_via_last_reviewed(monkeypatch):
    # `PRICEBOOK_DEV_FRESHNESS` is checked *before* `APP_ENV`, so setting the
    # environment alone left this test at the mercy of whatever another suite had
    # exported - it passed alone and failed in a full run. Say which mode we mean.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PRICEBOOK_DEV_FRESHNESS", "1")

    book = {
        "_id": "abc",
        "vendor": "rockwood",
        "effective": "2026-09-16",
        "lastReviewed": "2017-01-01",
    }
    decorated = await view.decorate(book)

    assert decorated["stale"] is True
    assert decorated["staleReferenceField"] == "lastReviewed"
