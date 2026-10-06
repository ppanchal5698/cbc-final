"""Who keeps each data set current, and when it is due for review (NFR-10,
requirements 6.3: "every set carries a version, effective date, and 'stale
after' date", with a named owner).

Versions and effective dates are the store's: every change archives the set it
replaced. The owners and cadences below are the requirements' proposal, for CBC
to rename. A set past its review is shown as due, never refused - pricing still
reads it; the price books carry their own stewardship on their own screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cbc.modules.pricing.api import reference_store

# family -> (owner, cadence, months between reviews; None when it changes on an event)
STEWARDS: dict[str, tuple[str, str, int | None]] = {
    "vendor_tiers": ("Purchasing", "on each price memo, reviewed quarterly", 3),
    "hager_special_nets": ("Purchasing", "on each price memo, reviewed quarterly", 3),
    "margins": ("Estimating Lead", "annually, and on change", 12),
    "hager_top10_stock": ("Estimating Lead", "quarterly", 3),
    "allegion_stock": ("Estimating Lead", "quarterly", 3),
    "special_customer_margins": ("Sales Mgmt / Estimating Lead", "on account change", None),
    "tax": ("Finance / IT", "on change", None),
}


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def overview(now: datetime | None = None) -> list[dict[str, Any]]:
    """Each stewarded set: its owner and cadence, when it last changed and by whom,
    and when it is next due. A set nobody has saved since the seed is due now."""
    moment = now or datetime.now(timezone.utc)
    rows = []
    for family, (owner, cadence, months) in STEWARDS.items():
        stamp = reference_store.family_stamp_sync(family) or {}
        updated = _utc(stamp["updatedAt"]) if stamp.get("updatedAt") else None
        review_due = updated + timedelta(days=round(months * 365 / 12)) if updated and months else None
        rows.append({
            "family": family, "owner": owner, "cadence": cadence,
            "updatedAt": updated, "updatedBy": stamp.get("updatedBy"), "reviewDue": review_due,
            "due": bool(months) and (review_due is None or review_due <= moment),
        })
    return rows
