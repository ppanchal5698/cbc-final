"""POST /api/projects/{code}/line-items/{item_id}/resolve-duplicate - keep one reading, or both.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException

from cbc.modules.extraction.api.openings import LINES_CONFIRMED
from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.shared import events
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/{item_id}/resolve-duplicate")
async def resolve_duplicate(
    code: str, item_id: str, actor: Actor, keep: str = Body(embed=True, default="one")
) -> dict:
    """Keep one reading of a duplicated line, or keep both as separate lines."""
    project = await load(code)
    item = await openings().find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")
    if keep not in ("one", "both"):
        raise HTTPException(400, "keep must be 'one' or 'both'")

    if keep == "one" and item.get("duplicateOf"):
        await openings().delete_one({"_id": item["_id"]})
        await audit.record(
            "line_item.duplicate_dropped",
            actor,
            {"projectId": project["_id"], "lineItemId": item["_id"]},
        )
        return {"kept": "one", "removed": str(item["_id"])}

    await openings().update_one(
        {"_id": item["_id"]},
        {
            "$set": {
                "status": "clear",
                "duplicateOf": None,
                "confirmedBy": actor,
                "confirmedAt": _now(),
            }
        },
    )
    await audit.record(
        "line_item.duplicate_kept",
        actor,
        {"projectId": project["_id"], "lineItemId": item["_id"]},
        after=keep,
    )
    await events.publish(LINES_CONFIRMED, project_id=project["_id"], count=1)
    return {"kept": keep, "lineItem": serialise(await openings().find_one({"_id": item["_id"]}))}
