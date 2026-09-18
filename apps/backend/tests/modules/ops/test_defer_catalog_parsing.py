"""Optional CATALOG_PARSE_WAIT deferral for match_and_price."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_defer_catalog_parsing_is_off_by_default(monkeypatch):
    from cbc.modules.ops.api import worker

    monkeypatch.delenv("CATALOG_PARSE_WAIT", raising=False)
    job = {
        "type": "match_and_price",
        "status": "running",
        "_id": "x",
    }
    assert await worker.defer_if_catalog_parsing(job) is None


@pytest.mark.asyncio
async def test_defer_catalog_parsing_ignores_bid_jobs(monkeypatch):
    from cbc.modules.ops.api import worker

    monkeypatch.setenv("CATALOG_PARSE_WAIT", "1")
    job = {
        "type": "extract_bid_set",
        "status": "running",
        "_id": "x",
    }
    assert await worker.defer_if_catalog_parsing(job) is None
