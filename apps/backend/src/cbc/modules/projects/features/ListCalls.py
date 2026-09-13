"""GET /api/projects/{code}/calls - the calls, notes and RFIs logged against a bid.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure.collections import calls
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/calls", tags=["calls"])


@router.get("")
async def list_calls(code: str, limit: int = Query(default=100, le=500)) -> dict:
    project = await load(code)
    entries = (
        await calls().find({"projectId": project["_id"]})
        .sort("createdAt", -1)
        .to_list(limit)
    )
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.get("kind", "call")] = counts.get(entry.get("kind", "call"), 0) + 1

    open_rfis = await calls().count_documents(
        {
            "projectId": project["_id"],
            "kind": "rfi",
            "$or": [{"resolvedAt": None}, {"resolvedAt": {"$exists": False}}],
        }
    )

    return {
        "calls": serialise(entries),
        "count": len(entries),
        "counts": counts,
        "openRfis": open_rfis,
    }
