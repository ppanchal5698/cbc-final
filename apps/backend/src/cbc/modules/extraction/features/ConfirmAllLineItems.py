"""POST /api/projects/{code}/line-items/confirm-all - confirm everything still flagged.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/confirm-all")
async def confirm_all(code: str, actor: Actor) -> dict:
    """Confirm everything still flagged for review, in one action."""
    project = await load(code)
    result = await openings().update_many(
        {"projectId": project["_id"], "status": {"$in": ["needs_look", "duplicate"]}},
        {"$set": {"status": "clear", "confirmedBy": actor, "confirmedAt": _now()}},
    )
    await audit.record(
        "line_item.confirm_all",
        actor,
        {"projectId": project["_id"]},
        after={"confirmed": result.modified_count},
    )
    return {"confirmed": result.modified_count}
