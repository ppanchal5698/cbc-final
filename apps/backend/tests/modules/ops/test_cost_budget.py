"""Cost budget helpers and claim gating."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from cbc.modules.ops.api import cost_budget


def test_caps_disabled_by_default(monkeypatch, tmp_path) -> None:
    # CBC_ENV_FILE is pinned at an empty file because the caps now fall back to
    # `.env`. Without it this passes or fails depending on whether the checkout
    # it runs in happens to have a cap written there.
    monkeypatch.setenv("CBC_ENV_FILE", str(tmp_path / "empty.env"))
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_DAY", raising=False)
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_PROJECT", raising=False)
    assert cost_budget.caps_enabled() is False
    assert asyncio.run(cost_budget.over_budget(project_id=ObjectId())) is None


def test_a_cap_in_the_env_file_is_honoured(monkeypatch, tmp_path) -> None:
    """Compose passes neither cap through, so `.env` is the only place it lives.

    Both were set in `.env` and read as unset: the worker claimed every job with
    no ceiling at all, which is silent - an absent cap looks exactly like a cap
    that has not been reached.
    """
    target = tmp_path / ".env"
    target.write_text(
        "WORKER_MAX_COST_USD_PER_DAY=20\nWORKER_MAX_COST_USD_PER_PROJECT=50\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CBC_ENV_FILE", str(target))
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_DAY", raising=False)
    monkeypatch.delenv("WORKER_MAX_COST_USD_PER_PROJECT", raising=False)

    assert cost_budget.day_cap_usd() == 20.0
    assert cost_budget.project_cap_usd() == 50.0


def test_the_process_env_still_wins(monkeypatch, tmp_path) -> None:
    target = tmp_path / ".env"
    target.write_text("WORKER_MAX_COST_USD_PER_DAY=20\n", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(target))
    monkeypatch.setenv("WORKER_MAX_COST_USD_PER_DAY", "5")

    assert cost_budget.day_cap_usd() == 5.0


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

    monkeypatch.setattr(cost_budget, "run_metrics", lambda: _DB.run_metrics)
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
    from cbc.modules.ops.features import WorkerLoop as runtime

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

    monkeypatch.setattr(runtime, "jobs_collection", lambda: _DB.jobs)
    monkeypatch.setattr(runtime, "CLAIMABLE_TYPES", {"extract_bid_set"})
    monkeypatch.setattr(
        "cbc.modules.ops.api.cost_budget.over_budget",
        AsyncMock(return_value="daily spend $2.00 >= cap $1.00"),
    )
    monkeypatch.setattr(
        "cbc.modules.ops.api.alerts.notify", lambda *a, **k: True
    )
    assert asyncio.run(runtime.claim()) is None


def test_spend_usd_excludes_local_providers(monkeypatch) -> None:
    """Free NIM/Ollama legs must not walk the USD cap up.

    The CLI prices every run off its Anthropic table, so a local leg lands in
    runMetrics with a real-looking totalCostUsd. Counting it wedged the worker:
    $18 of phantom NIM spend tripped a $20 day cap and every job stayed queued.
    """
    captured: dict = {}

    class _Agg:
        async def to_list(self, _n):
            return [{"_id": None, "total": 1.0}]

    class _RM:
        def aggregate(self, pipeline):
            captured["match"] = pipeline[0]["$match"]
            return _Agg()

    monkeypatch.setattr(cost_budget, "run_metrics", lambda: _RM())
    asyncio.run(cost_budget.spend_usd(since=datetime.now(timezone.utc)))
    assert captured["match"]["provider.mode"] == {"$nin": ["ollama", "nim"]}
