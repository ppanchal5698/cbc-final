"""GET /api/projects/{code}/line-items - a bid's openings, filtered, with counts per state.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.extraction.domain.openings import MAX_OPENINGS_LISTED
from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.projects.api.lookup import load
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


FILTERS = {
    "all": {},
    "needs_look": {"status": "needs_look"},
    "duplicate": {"status": "duplicate"},
    "by_hand": {"status": "by_hand"},
    "clear": {"status": "clear"},
}


@router.get("")
async def list_line_items(
    code: str, filter: str = "all", alternate: str | None = None
) -> dict[str, Any]:
    project = await load(code)
    if filter not in FILTERS:
        raise HTTPException(400, f"unknown filter {filter!r}; try {sorted(FILTERS)}")

    # alternate="" selects the base bid explicitly; omitting it shows everything.
    query: dict[str, Any] = {"projectId": project["_id"], **FILTERS[filter]}
    if alternate is not None:
        query["alternateGroup"] = alternate or None
    items = await openings().find(query).sort([("mark", 1), ("createdAt", 1)]).to_list(MAX_OPENINGS_LISTED)

    counts_raw = await openings().aggregate(
        [{"$match": {"projectId": project["_id"]}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ).to_list(20)
    counts = {row["_id"]: row["n"] for row in counts_raw}

    return {
        "lineItems": serialise(items),
        "counts": {
            "all": sum(counts.values()),
            "needs_look": counts.get("needs_look", 0),
            "duplicate": counts.get("duplicate", 0),
            "by_hand": counts.get("by_hand", 0),
            "clear": counts.get("clear", 0),
        },
    }
