"""A provider usage limit is a clock, not a defect.

`claude --output-format stream-json` emits `rate_limit_event` "when rate limit
info changes", which is mostly while everything is fine - `status` is `allowed`
far more often than not. Only a `rejected` one means this run was stopped, and it
carries `resetsAt`: the moment capacity comes back.

That matters because the queue's ladder is 30s, then 60s, then dead-lettered -
under two minutes, against a five-hour subscription window. Without the reset
time a rate-limited bid cannot survive its own retries.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from cbc.modules.ops.api import worker
from cbc.modules.ops.api.claude_cli import _interpret, rate_limit_reset


def _event(status: str, resets_at: int | None = None, window: str = "five_hour") -> str:
    info: dict[str, object] = {"status": status, "rateLimitType": window}
    if resets_at is not None:
        info["resetsAt"] = resets_at
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": info})


RESET = int(datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc).timestamp())


def test_only_a_refusal_counts_as_a_rate_limit():
    """`allowed` events carry a `resetsAt` too - it is just when the window rolls."""
    healthy = "\n".join([_event("allowed", RESET), _event("allowed_warning", RESET)])

    assert rate_limit_reset(healthy) is None
    assert rate_limit_reset("\n".join([healthy, _event("rejected", RESET)])) == datetime(
        2026, 9, 21, 18, 0, tzinfo=timezone.utc
    )


def test_a_reset_in_milliseconds_is_still_read_as_a_time():
    assert rate_limit_reset(_event("rejected", RESET * 1000)) == datetime(
        2026, 9, 21, 18, 0, tzinfo=timezone.utc
    )


def test_approaching_a_limit_is_not_hitting_one():
    """The CLI says "Approaching your 5-hour usage limit" while working fine.

    Matching that phrase would fail healthy runs, so the markers have to be
    stop-phrases only.
    """
    result = _interpret(
        stdout="Approaching your 5-hour usage limit\n" + _event("allowed_warning", RESET),
        stderr="",
        returncode=0,
        timeout=60,
        redact_values=None,
    )
    assert result.ok, f"a warning failed the run: {result.error!r}"
    assert result.retry_at is None


def test_a_stopped_run_carries_the_reset_time_up():
    result = _interpret(
        stdout=_event("rejected", RESET) + "\nusage limit reached",
        stderr="",
        returncode=1,
        timeout=60,
        redact_values=None,
    )
    assert not result.ok
    assert result.error_code == "rate_limited"
    assert result.retry_at == datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    assert not result.permanent, "the limit lifts; the job should get another go"


def test_the_queue_waits_for_the_window_instead_of_its_own_ladder():
    soon = datetime.now(timezone.utc) + timedelta(hours=4)
    assert worker.rate_limit_wait(soon) == soon

    # Already passed while the job sat on the queue: go now, not into the past.
    passed = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert worker.rate_limit_wait(passed) > passed

    assert worker.rate_limit_wait(None) is None


def test_a_weekly_limit_is_not_something_to_sit_on_the_queue_for():
    """Past a day it is a weekly window. A bid queued for days, silently, is worse
    than one that failed and said why."""
    next_week = datetime.now(timezone.utc) + timedelta(days=3)
    assert worker.rate_limit_wait(next_week) is None
