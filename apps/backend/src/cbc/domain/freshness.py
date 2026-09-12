"""How old a P21 last-PO cost or a vendor sheet may be before it stops counting.

The rule is the workbook's, not ours. Requirements Matrix 6.2:

    "Freshness: cost older than ~6-8 months is unreliable; 3-4 years must be
     discarded."

restated at `docs/collections.mongodb.md` §7 row 19. The defaults below take the
conservative end of each stated range - 6 months, then 3 years - because a cost
that is quietly too old produces a wrong quote, while one flagged early produces
a manual line an estimator can price. CBC may widen them to 8 months / 4 years
from Settings without touching code; the range is theirs to close.

These were 24 months and 30 months until this change: three to four times more
permissive than 6.2 on the first threshold and, oddly, stricter than it on the
second. The numbers had also been restated as if they were the CBC rule in the
p21-connector tool description, the cost-sourcing memory file and the
p21-read-only rule, so five places moved together.

Admins can change the windows from Settings. Those live values are loaded in
`cbc.services.freshness`; this module is the rule itself: defaults, conversion,
and classification with no I/O.
"""
from __future__ import annotations

from typing import Any

# Matrix 6.2, conservative end of each range. Settings may widen to 8 / 48.
FRESH_MONTHS = 6
DISCARD_AFTER_MONTHS = 36  # 3 years
MAX_MONTHS = 120


def days_from_months(months: int) -> int:
    """Round-half-up, so 6 months is 183 days and 36 months is 1095."""
    return int(months * 365 / 12 + 0.5)


FRESH_DAYS = days_from_months(FRESH_MONTHS)
DISCARD_AFTER_DAYS = days_from_months(DISCARD_AFTER_MONTHS)

# A vendor price sheet is a different question from a purchase-order price, and a
# different rule answers it. Price changes arrive as dated memos with a protection
# window (Matrix 6.3), and `.claude/rules/data-stewardship.md` warns past ~24
# months. This used to be an alias for FRESH_DAYS, which was harmless only while
# both windows happened to be 24 months; correcting the cost rule to Matrix 6.2
# would otherwise have quietly cut price-book staleness to six months as well.
CATALOG_STALE_MONTHS = 24
CATALOG_STALE_DAYS = days_from_months(CATALOG_STALE_MONTHS)


def months_from_days(days: int) -> int:
    return max(1, int(days * 12 / 365 + 0.5))


def _period_phrase(months: int) -> str:
    """Human label for a month count: 6 -> "6 months", 36 -> "3 years"."""
    if months < 12:
        return f"{months} months"
    years = months / 12
    if years.is_integer():
        return "1 year" if years == 1 else f"{years:.0f} years"
    return f"{years:g} years"


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
