"""Cost budget helpers and claim gating."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from cbc.services import cost_budget


def test_caps_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_DAY", raising=False)
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_PROJECT", raising=False)
    assert cost_budget.caps_enabled() is False
    assert asyncio.run(cost_budget.over_budget(project_id=ObjectId())) is None


def test_spend_usd_sums_aggregation(monkeypatch) -> None:
    class _Agg:
        def __init__(self, rows):
            self._rows = rows

        async def to_list(self, _n):
            return self._rows

    class _RM:
        def aggregate(self, pipeline):
            assert pipeline[0]["$match"]["totalCostUsd"]["$type"] == "number"
            return _Agg([{"_id": None, "total": 12.5}])

    class _DB:
        run_metrics = _RM()

    monkeypatch.setattr(cost_budget, "db", _DB())
    spent = asyncio.run(
        cost_budget.spend_usd(since=datetime.now(timezone.utc))
    )
    assert spent == 12.5


def test_over_budget_day_cap(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_MAX_COST_USD_PER_DAY", "10")
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_PROJECT", raising=False)
    monkeypatch.setattr(
        cost_budget, "spend_usd", AsyncMock(return_value=10.0)
    )
    reason = asyncio.run(cost_budget.over_budget(project_id=None))
    assert reason is not None
    assert "daily spend" in reason


def test_claim_skips_when_over_budget(monkeypatch) -> None:
    from cbc.worker_kit import runtime

    monkeypatch.setenv("WORKER_MAX_COST_USD_PER_DAY", "1")
    candidate = {
        "_id": ObjectId(),
        "type": "extract_bid_set",
        "projectId": ObjectId(),
        "status": "queued",
    }

    class _Jobs:
        async def find_one(self, *a, **k):
            return candidate

        async def find_one_and_update(self, *a, **k):
            raise AssertionError("must not claim when over budget")

    class _DB:
        jobs = _Jobs()

    monkeypatch.setattr(runtime, "db", _DB())
    monkeypatch.setattr(runtime, "CLAIMABLE_TYPES", {"extract_bid_set"})
    monkeypatch.setattr(
        "cbc.services.cost_budget.over_budget",
        AsyncMock(return_value="daily spend $2.00 >= cap $1.00"),
    )
    monkeypatch.setattr(
        "cbc.services.alerts.notify", lambda *a, **k: True
    )
    assert asyncio.run(runtime.claim()) is None
