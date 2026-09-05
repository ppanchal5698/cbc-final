"""Spend ops aggregation unit tests (fake Mongo cursor)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cbc.services import spend_ops


class _Agg:
    def __init__(self, rows):
        self._rows = rows
        self._i = 0

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row

    async def to_list(self, _n):
        return list(self._rows)


class _Find:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def to_list(self, _n):
        return list(self._docs)


def test_summary_rolls_up(monkeypatch) -> None:
    calls: list = []

    class _RM:
        def aggregate(self, pipeline):
            calls.append(pipeline)
            stage = pipeline[1]["$group"]["_id"]
            if stage is None:
                return _Agg([{"_id": None, "totalCostUsd": 12.5, "runs": 3}])
            if stage == "$jobType":
                return _Agg(
                    [{"_id": "extract_bid_set", "totalCostUsd": 12.5, "runs": 3}]
                )
            return _Agg(
                [
                    {
                        "_id": {"projectId": "p1", "projectSlug": "demo"},
                        "totalCostUsd": 12.5,
                        "runs": 3,
                    }
                ]
            )

        def find(self, *_a, **_k):
            return _Find(
                [
                    {
                        "_id": "j1:1",
                        "jobId": "j1",
                        "jobType": "extract_bid_set",
                        "projectSlug": "demo",
                        "totalCostUsd": 4.0,
                        "tokens": {"cacheRead": 80, "cacheCreate": 20},
                        "startedAt": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            )

    class _DB:
        run_metrics = _RM()

    monkeypatch.setattr(spend_ops, "db", _DB())
    monkeypatch.setattr(spend_ops.cost_budget, "day_cap_usd", lambda: 10.0)
    monkeypatch.setattr(spend_ops.cost_budget, "project_cap_usd", lambda: 5.0)

    result = asyncio.run(spend_ops.summary(hours=24))
    assert result["totalCostUsd"] == 12.5
    assert result["overDailyCap"] is True
    assert result["byType"][0]["jobType"] == "extract_bid_set"
    assert result["byProject"][0]["overProjectCap"] is True
    assert result["recent"][0]["cacheHitRatio"] == 0.8
