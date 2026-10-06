"""Whether a priced line's cost is still backed by a current price sheet.

One rule, one implementation: the quote grid marks the line and the proposal
gate counts the same lines, so they cannot disagree about what "lapsed" means.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from cbc.modules.ops.api.freshness_rules import classify

# Costs read off a dated sheet: their age is the sheet's, and a sheet is judged by
# its review window (Matrix 6.3), not by the six months a purchase order gets.
_SHEET_SOURCES = {"LIST_X_MULTIPLIER", "SPECIAL_NET", "CATALOG_BASELINE", "BOOK_PRICE"}


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _entered(line: dict[str, Any]) -> date | None:
    """When the cost was last typed or applied - the latest edit that set it."""
    edits = [o for o in line.get("overrides") or [] if "cost" in (o.get("after") or {})]
    if edits:
        return _day(max(edits, key=lambda o: str(o.get("at")))["at"])
    return _day(line.get("pricedAt")) or _day(line.get("createdAt"))


def cost_freshness(line: dict[str, Any], bands: Any, today: date | None = None) -> dict[str, Any] | None:
    """How old a line's cost is, by the rule for where it came from (FR-6a).

    `status` is fresh / aging / unreliable / stale, or unknown when the date the
    cost stands on was never recorded - the requirements' green, amber, red and
    blocked. None for a line with no cost: there is nothing to age.
    """
    if line.get("cost") is None:
        return None
    source = str(line.get("costSource") or "MANUAL").upper()
    if source == "P21_LAST_PO":
        as_of, basis = _day(line.get("lastPoDate")), "last PO"
    elif source in _SHEET_SOURCES:
        as_of, basis = _day(line.get("multiplierEffectiveDate")), "sheet effective"
    else:
        as_of, basis = _entered(line), "entered"
    if as_of is None:
        return {"status": "unknown", "asOf": None, "basis": basis,
                "guidance": f"No {basis} date recorded - check where this cost came from."}

    age = ((today or date.today()) - as_of).days
    if source in _SHEET_SOURCES:
        verdict = classify(age, bands.catalog_stale_days, bands.discard_after_days)
        if verdict["status"] == "aging":  # a PO's grace year; a sheet past its window is past it
            verdict = {**verdict, "status": "unreliable"}
    else:
        verdict = classify(age, bands.fresh_days, bands.discard_after_days)
    return {"status": verdict["status"], "asOf": as_of.isoformat(), "basis": basis,
            "guidance": verdict["guidance"]}


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
