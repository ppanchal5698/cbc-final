"""A cost is lapsed when its sheet is past the review window - and only then.

This is the one rule that blocks a hand-off, so it is
worth pinning on its own: the quote grid marks these lines and the proposal
gate counts them, from this single function.
"""
from __future__ import annotations

from datetime import date, timedelta

from cbc.modules.quoting.domain.freshness import is_lapsed


def _effective(days_ago: int) -> dict:
    return {"multiplierEffectiveDate": (date.today() - timedelta(days=days_ago)).isoformat()}


def test_a_sheet_inside_the_window_is_current():
    assert is_lapsed(_effective(30), stale_days=730) is False


def test_a_sheet_past_the_window_is_lapsed():
    assert is_lapsed(_effective(800), stale_days=730) is True


def test_the_boundary_day_is_not_yet_lapsed():
    # Strictly past, so a sheet exactly at the window still prices.
    assert is_lapsed(_effective(730), stale_days=730) is False
    assert is_lapsed(_effective(731), stale_days=730) is True


def test_no_effective_date_is_not_lapsed():
    # Nothing is known either way; an undated sheet is chased on the price
    # books screen, not by blocking a hand-off on a guess.
    assert is_lapsed({}, stale_days=730) is False
    assert is_lapsed({"multiplierEffectiveDate": None}, stale_days=730) is False


def test_an_unparseable_date_does_not_blow_up_the_gate():
    assert is_lapsed({"multiplierEffectiveDate": "last thursday"}, stale_days=730) is False
    assert is_lapsed({"multiplierEffectiveDate": "2026-13-45"}, stale_days=730) is False


# ── FR-6a: every cost shows how old it is ────────────────────────────────────

from cbc.modules.ops.api.freshness import DEFAULTS as BANDS  # noqa: E402
from cbc.modules.quoting.domain.freshness import cost_freshness  # noqa: E402

TODAY = date(2026, 10, 6)


def _ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def _status(line: dict) -> str | None:
    found = cost_freshness({"cost": 10.0, **line}, BANDS, today=TODAY)
    return found and found["status"]


def test_a_last_po_ages_green_amber_red_then_blocked():
    """Requirements 5.2: under 6 months, 6-12, over 12, over 3 years."""
    po = {"costSource": "P21_LAST_PO"}
    assert _status({**po, "lastPoDate": _ago(90)}) == "fresh"
    assert _status({**po, "lastPoDate": _ago(270)}) == "aging"
    assert _status({**po, "lastPoDate": _ago(500)}) == "unreliable"
    assert _status({**po, "lastPoDate": _ago(1200)}) == "stale"


def test_a_sheet_is_current_for_its_whole_review_window():
    """A nine-month-old price book is this year's book, not an aging cost."""
    sheet = {"costSource": "LIST_X_MULTIPLIER"}
    assert _status({**sheet, "multiplierEffectiveDate": _ago(270)}) == "fresh"
    assert _status({**sheet, "multiplierEffectiveDate": _ago(800)}) == "unreliable"
    assert _status({**sheet, "multiplierEffectiveDate": _ago(1200)}) == "stale"


def test_a_typed_cost_is_as_old_as_the_edit_that_set_it():
    line = {
        "costSource": "DISTRIBUTOR_MANUAL",
        "pricedAt": _ago(20),
        "overrides": [
            {"at": _ago(400), "after": {"cost": 9.0}},
            {"at": _ago(300), "after": {"margin": 0.3}},
        ],
    }
    assert _status(line) == "unreliable"
    assert cost_freshness({"cost": 10.0, **line}, BANDS, today=TODAY)["basis"] == "entered"


def test_an_unrecorded_date_says_so_and_no_cost_has_no_age():
    assert _status({"costSource": "P21_LAST_PO"}) == "unknown"
    assert cost_freshness({"cost": None}, BANDS, today=TODAY) is None
