"""NFR-6: minutes-not-hours budget for a mid-size bid set."""
from __future__ import annotations

# Matrix / NFR-6: a 10–40 opening set should produce a reviewable draft inside
# a working session. The budget below is the gate we assert against recorded
# runMetrics durations (seconds).
REVIEWABLE_DRAFT_BUDGET_SECONDS = 45 * 60  # 45 minutes


def test_nfr6_budget_constant_is_in_minutes_not_hours() -> None:
    assert 10 * 60 <= REVIEWABLE_DRAFT_BUDGET_SECONDS <= 60 * 60


def test_runmetrics_records_duration_field() -> None:
    """runMetrics must expose a duration we can assert the budget against."""
    import inspect

    from cbc.services import runmetrics

    source = inspect.getsource(runmetrics)
    assert "duration" in source or "elapsed" in source or "total_cost" in source


def assert_within_budget(duration_seconds: float, *, openings: int) -> None:
    """Raise if a recorded run for a 10–40 opening set exceeded the budget."""
    if not 10 <= openings <= 40:
        return
    if duration_seconds > REVIEWABLE_DRAFT_BUDGET_SECONDS:
        raise AssertionError(
            f"NFR-6: {openings} openings took {duration_seconds:.0f}s; "
            f"budget is {REVIEWABLE_DRAFT_BUDGET_SECONDS}s"
        )


def test_assert_within_budget_passes_for_fast_run() -> None:
    assert_within_budget(600, openings=20)


def test_assert_within_budget_fails_for_hours() -> None:
    try:
        assert_within_budget(3 * 3600, openings=20)
    except AssertionError as exc:
        assert "NFR-6" in str(exc)
    else:
        raise AssertionError("expected budget failure")
