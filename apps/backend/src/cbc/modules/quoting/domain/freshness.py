"""Whether a priced line's cost is still backed by a current price sheet.

One rule, one implementation: the quote grid marks the line and the proposal
gate counts the same lines, so they cannot disagree about what "lapsed" means.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def is_lapsed(line: dict[str, Any], stale_days: int) -> bool:
    """True when the sheet this cost came from is past the review window.

    A lapsed price is not wrong, but it is unverified - the estimator decides.
    A line with no effective date is not lapsed: nothing is known about it
    either way, and the price books screen is where an undated sheet is chased.
    """
    effective = line.get("multiplierEffectiveDate")
    if not effective:
        return False
    try:
        return (date.today() - date.fromisoformat(str(effective))).days > stale_days
    except ValueError:
        return False
