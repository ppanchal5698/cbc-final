"""A cost is lapsed when its sheet is past the review window - and only then.

This is the one rule that blocks a hand-off (data-stewardship.md), so it is
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
