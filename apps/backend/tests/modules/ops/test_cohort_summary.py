"""W1b: cohort roll-up aggregation and the changedFrom diff (fake Mongo cursor)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from cbc.modules.ops.features import CohortSummary as cohort_ops
from tests.modules.ops.test_spend_ops import _Agg


def _rows():
    now = datetime.now(timezone.utc)
    # Two cohorts of the same job type. Newer first, as $sort lastRun desc yields.
    # They differ only in toolProfiles and one agent hash; runtime is identical.
    newer_ctx = {
        "toolProfiles": "tpB",
        "agents": {"pricing-engineer": "peB"},
        "runtime": "r1",
    }
    older_ctx = {
        "toolProfiles": "tpA",
        "agents": {"pricing-engineer": "peA"},
        "runtime": "r1",
    }
    return [
        {
            "_id": {"jobType": "match_and_price", "context": newer_ctx},
            "runs": 2,
            "costs": [1.0, 1.2],
            "durations": [1000, 1200],
            "toolCalls": [10, 12],
            "firstRun": now - timedelta(hours=1),
            "lastRun": now,
        },
        {
            "_id": {"jobType": "match_and_price", "context": older_ctx},
            "runs": 2,
            "costs": [2.0, 2.0],
            "durations": [3000, 3000],
            "toolCalls": [40, 40],
            "firstRun": now - timedelta(days=2),
            "lastRun": now - timedelta(days=1),
        },
    ]


def test_cohorts_roll_up_with_median_and_mean(monkeypatch) -> None:
    class _RM:
        def aggregate(self, _pipeline):
            return _Agg(_rows())

    monkeypatch.setattr(cohort_ops, "run_metrics", lambda: _RM())

    result = asyncio.run(cohort_ops.summary(job_type="match_and_price", days=30))
    cohorts = result["cohorts"]
    assert len(cohorts) == 2

    newer, older = cohorts[0], cohorts[1]
    assert newer["costUsd"]["median"] == 1.1
    assert newer["costUsd"]["mean"] == 1.1
    assert older["costUsd"]["median"] == 2.0
    assert newer["runs"] == 2
    # Distinct config -> distinct cohort id.
    assert newer["cohortId"] != older["cohortId"]


def test_changed_from_names_what_moved_and_the_cost_delta(monkeypatch) -> None:
    class _RM:
        def aggregate(self, _pipeline):
            return _Agg(_rows())

    monkeypatch.setattr(cohort_ops, "run_metrics", lambda: _RM())

    result = asyncio.run(cohort_ops.summary(job_type="match_and_price", days=30))
    newer, older = result["cohorts"]

    # The oldest cohort has nothing before it to diff against.
    assert older["changedFrom"] is None
    changed = newer["changedFrom"]
    assert changed is not None
    assert changed["keys"] == ["agents.pricing-engineer", "toolProfiles"]
    # median 1.1 vs 2.0 -> -45.0%
    assert changed["deltaPct"]["costUsd"] == -45.0


def test_a_lone_cohort_has_no_changed_from(monkeypatch) -> None:
    class _RM:
        def aggregate(self, _pipeline):
            return _Agg(_rows()[:1])

    monkeypatch.setattr(cohort_ops, "run_metrics", lambda: _RM())

    result = asyncio.run(cohort_ops.summary(days=30))
    assert len(result["cohorts"]) == 1
    assert result["cohorts"][0]["changedFrom"] is None
