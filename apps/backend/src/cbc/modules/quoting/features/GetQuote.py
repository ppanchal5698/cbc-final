"""GET /api/projects/{code}/quote - priced lines by division, computed, with the stored quote.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from cbc.modules.ops.api import freshness as freshness_settings
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.infrastructure.collections import quotes
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


def _lapsed(line: dict[str, Any], stale_days: int) -> bool:
    """True when the sheet this cost came from is past the review window.

    A lapsed price is not wrong, but it is unverified - the estimator decides.
    """
    effective = line.get("multiplierEffectiveDate")
    if not effective:
        return False
    try:
        return (date.today() - date.fromisoformat(str(effective))).days > stale_days
    except ValueError:
        return False


@router.get("")
async def get_quote(code: str) -> dict[str, Any]:
    project = await load(code)
    # Computed, not stored. This is a GET; it used to write a row per line and
    # upsert the totals on every page load and every four-second poll.
    totals, raw = await quote_service.totals_for(project)
    bands = await freshness_settings.load()
    lines = [
        {**serialise(line), "lapsed": _lapsed(line, bands.catalog_stale_days)}
        for line in raw
    ]

    groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = line.get("division") or "Other"
        group = groups.setdefault(key, {"division": key, "lines": [], "subtotal": 0.0})
        group["lines"].append(line)
        group["subtotal"] = round(group["subtotal"] + (line.get("extended") or 0), 2)

    quote = await quotes().find_one({"projectId": project["_id"]})
    edited = [line for line in lines if line.get("marginOverridden") or line.get("addedByHand")]

    return {
        "quote": serialise(quote),
        "groups": sorted(groups.values(), key=lambda g: g["division"]),
        "totals": totals,
        "lineCount": len(lines),
        "edited": {
            "count": len(edited),
            "firstId": edited[0]["id"] if edited else None,
        },
        "lapsedCount": sum(1 for line in lines if line["lapsed"]),
        "reviewWindowMonths": bands.catalog_stale_months,
    }
