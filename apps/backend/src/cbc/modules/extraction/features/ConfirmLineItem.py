"""POST /api/projects/{code}/line-items/{item_id}/confirm - keep an opening as read.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

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


@router.post("/{item_id}/confirm")
async def confirm_line_item(code: str, item_id: str, actor: Actor) -> dict:
    """Keep as is. The estimator has looked at the drawing and agrees."""
    project = await load(code)
    item = await openings().find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")

    await openings().update_one(
        {"_id": item["_id"]},
        {"$set": {"status": "clear", "confirmedBy": actor, "confirmedAt": _now()}},
    )
    await audit.record(
        "line_item.confirm", actor, {"projectId": project["_id"], "lineItemId": item["_id"]}
    )
    await events.publish(LINES_CONFIRMED, project_id=project["_id"], count=1)
    return serialise(await openings().find_one({"_id": item["_id"]}))
