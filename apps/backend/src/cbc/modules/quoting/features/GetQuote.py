"""GET /api/projects/{code}/quote - priced lines by division, computed, with the stored quote.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.ops.api import freshness as freshness_settings
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.freshness import is_lapsed
from cbc.modules.quoting.infrastructure.collections import quotes
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


@router.get("")
async def get_quote(code: str) -> dict[str, Any]:
    project = await load(code)
    # Computed, not stored. This is a GET; it used to write a row per line and
    # upsert the totals on every page load and every four-second poll.
    totals, raw = await quote_service.totals_for(project)
    bands = await freshness_settings.load()
    lines = [
        {**serialise(line), "lapsed": is_lapsed(line, bands.catalog_stale_days)}
        for line in raw
    ]

    # Grouped by opening (the hardware group the pass assigned), not by
    # division: an estimator prices and checks a door at a time, and the
    # proposal is already laid out that way. `division` stays on the group for
    # readers that key off it, and is the fallback for a line with no opening.
    groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        division = line.get("division") or "Other"
        key = line.get("group") or division
        group = groups.setdefault(
            key,
            {"group": key, "division": division, "lines": [], "subtotal": 0.0},
        )
        group["lines"].append(line)
        group["subtotal"] = round(group["subtotal"] + (line.get("extended") or 0), 2)

    quote = await quotes().find_one({"projectId": project["_id"]})
    edited = [line for line in lines if line.get("marginOverridden") or line.get("addedByHand")]

    return {
        "quote": serialise(quote),
        "groups": sorted(groups.values(), key=lambda g: str(g["group"])),
        "totals": totals,
        "lineCount": len(lines),
        "edited": {
            "count": len(edited),
            "firstId": edited[0]["id"] if edited else None,
        },
        "lapsedCount": sum(1 for line in lines if line["lapsed"]),
        "reviewWindowMonths": bands.catalog_stale_months,
    }
