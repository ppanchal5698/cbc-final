"""The freshness windows, against the requirement that sets them.

Requirements Matrix 6.2, restated at `docs/collections.mongodb.md` §7 row 19:

    "Freshness: cost older than ~6-8 months is unreliable; 3-4 years must be
     discarded."

The defaults take the conservative end of each range. These tests cite the
workbook rather than the code, because the previous version of this file pinned
730 and 913 days as "the published defaults" - numbers three to four times more
permissive than 6.2 on the first threshold - and so locked the deviation in.
"""
from __future__ import annotations

from cbc.modules.ops.api import freshness_rules as core
from cbc.modules.ops.api.freshness import DEFAULTS, from_document

# Matrix 6.2, as stated. The defaults must sit inside these ranges.
UNRELIABLE_AFTER_MONTHS = (6, 8)
DISCARD_AFTER_YEARS = (3, 4)


def test_the_cost_window_is_the_one_the_workbook_states() -> None:
    low, high = UNRELIABLE_AFTER_MONTHS
    assert low <= core.FRESH_MONTHS <= high, (
        f"a P21 cost is treated as fresh for {core.FRESH_MONTHS} months; "
        f"Matrix 6.2 says it is unreliable past ~{low}-{high}"
    )
    low, high = DISCARD_AFTER_YEARS
    assert low * 12 <= core.DISCARD_AFTER_MONTHS <= high * 12, (
        f"a P21 cost is discarded after {core.DISCARD_AFTER_MONTHS} months; "
        f"Matrix 6.2 says {low}-{high} years"
    )


def test_the_price_sheet_window_is_a_different_rule() -> None:
    """Matrix 6.3 price memos, not 6.2 purchase orders.

    CATALOG_STALE_DAYS was an alias for FRESH_DAYS. Harmless while both windows
    were 24 months; correcting the cost rule would otherwise have cut price-book
    staleness to six months as a side effect nobody asked for.
    """
    assert core.CATALOG_STALE_MONTHS == 24
    assert core.CATALOG_STALE_DAYS != core.FRESH_DAYS
    assert DEFAULTS.catalog_stale_days == core.CATALOG_STALE_DAYS
    assert DEFAULTS.fresh_days == core.FRESH_DAYS


def test_days_from_months_rounds_half_up() -> None:
    assert core.days_from_months(6) == 183
    assert core.days_from_months(24) == 730
    assert core.days_from_months(36) == 1095
    assert core.FRESH_DAYS == core.days_from_months(core.FRESH_MONTHS)
    assert core.DISCARD_AFTER_DAYS == core.days_from_months(core.DISCARD_AFTER_MONTHS)


def test_classify_default_bands() -> None:
    """A cost is usable for months, questionable for years, then not at all."""
    assert core.classify(30)["status"] == "fresh"
    assert core.classify(200)["status"] == "unreliable"
    assert core.classify(1200)["status"] == "stale"
    assert core.classify(-1)["status"] == "future_dated"

    # Only `fresh` may be quoted from without re-verification.
    assert core.classify(30)["usable"] is True
    for age in (200, 1200, -1):
        assert core.classify(age)["usable"] is False


def test_a_year_old_cost_is_no_longer_treated_as_fresh() -> None:
    """The regression this correction exists to prevent.

    At the old 24-month default a cost from last year was returned as
    `"status": "fresh", "usable": True, "Usable if there has been no price
    increase."` - and quoted.
    """
    verdict = core.classify(365)
    assert verdict["status"] == "unreliable"
    assert verdict["usable"] is False
    assert "re-verify" in verdict["guidance"]


def test_the_rule_text_reads_as_the_workbook_does() -> None:
    assert core.RULE == (
        "under ~6 months fresh; more than 6 months unreliable; "
        "more than 3 years discard"
    )


def test_period_phrase_speaks_months_then_years() -> None:
    assert core._period_phrase(6) == "6 months"
    assert core._period_phrase(12) == "1 year"
    assert core._period_phrase(30) == "2.5 years"
    assert core._period_phrase(36) == "3 years"


def test_from_document_falls_back_when_the_row_is_broken() -> None:
    assert from_document(None) == DEFAULTS
    assert from_document({"catalogStaleMonths": "nope"}) == DEFAULTS
    assert from_document({"catalogStaleMonths": 24, "discardAfterMonths": 12}) == DEFAULTS


def test_from_document_accepts_admin_months() -> None:
    bands = from_document({"catalogStaleMonths": 6, "discardAfterMonths": 12})
    assert bands.catalog_stale_days == core.days_from_months(6)
    assert bands.discard_after_days == core.days_from_months(12)
    assert "6 months" in bands.rule
