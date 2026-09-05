"""CBC freshness bands for P21 last-PO costs and vendor catalogs.

Defaults: a cost or sheet is fresh for about 24 months, unreliable after that,
and discarded after 2.5 years. Catalog `stale` uses the same 24-month window.

Admins can change the windows from Settings. Those live values are loaded in
`cbc.services.freshness`; this module stays the kernel: defaults, conversion,
and classification with no I/O.
"""
from __future__ import annotations

from typing import Any

FRESH_MONTHS = 24
DISCARD_AFTER_MONTHS = 30  # 2.5 years
MAX_MONTHS = 120


def days_from_months(months: int) -> int:
    """Round-half-up so 24 months is 730 days and 30 months is 913 (365 * 2.5)."""
    return int(months * 365 / 12 + 0.5)


FRESH_DAYS = days_from_months(FRESH_MONTHS)
DISCARD_AFTER_DAYS = days_from_months(DISCARD_AFTER_MONTHS)
CATALOG_STALE_DAYS = FRESH_DAYS


def months_from_days(days: int) -> int:
    return max(1, int(days * 12 / 365 + 0.5))


def _period_phrase(months: int) -> str:
    """Human label for a month count. 30 months is the published 2.5-year discard."""
    if months == 30:
        return "2.5 years"
    if months == 12:
        return "1 year"
    return f"{months} months"


def rule_text(fresh_months: int = FRESH_MONTHS, discard_months: int = DISCARD_AFTER_MONTHS) -> str:
    fresh = _period_phrase(fresh_months)
    discard = _period_phrase(discard_months)
    return (
        f"under ~{fresh} fresh; more than {fresh} unreliable; "
        f"more than {discard} discard"
    )


RULE = rule_text()


def classify(
    age_days: int,
    fresh_days: int = FRESH_DAYS,
    discard_after_days: int = DISCARD_AFTER_DAYS,
    fresh_months: int | None = None,
    discard_months: int | None = None,
) -> dict[str, Any]:
    """Status, usability, and guidance for a last-PO or sheet age in days."""
    fresh_label = _period_phrase(fresh_months if fresh_months is not None else months_from_days(fresh_days))
    discard_label = _period_phrase(
        discard_months if discard_months is not None else months_from_days(discard_after_days)
    )
    if age_days < 0:
        return {
            "status": "future_dated",
            "usable": False,
            "guidance": "PO date is in the future - verify.",
        }
    if age_days <= fresh_days:
        return {
            "status": "fresh",
            "usable": True,
            "guidance": "Usable if there has been no price increase.",
        }
    if age_days <= discard_after_days:
        return {
            "status": "unreliable",
            "usable": False,
            "guidance": (
                f"More than {fresh_label} old - re-verify against the vendor "
                "sheet before quoting."
            ),
        }
    return {
        "status": "stale",
        "usable": False,
        "guidance": f"More than {discard_label} old - discard. Do not quote from this.",
    }
