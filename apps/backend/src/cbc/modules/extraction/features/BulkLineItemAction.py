"""POST /api/projects/{code}/line-items/bulk - confirm or remove a selection.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from cbc.modules.extraction.domain.openings import BulkAction
from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/bulk")
async def bulk_action(code: str, body: BulkAction, actor: Actor) -> dict:
    """Confirm or remove a selection in one action.

    Same audit shape as the single-item paths, so a bulk confirm is as traceable
    as an individual one - it records how many, and which.
    """
    project = await load(code)
    ids = [oid(item_id) for item_id in body.ids]
    query = {"_id": {"$in": ids}, "projectId": project["_id"]}

    if body.action == "confirm":
        result = await openings().update_many(
            query,
            {"$set": {"status": "clear", "confirmedBy": actor, "confirmedAt": _now()}},
        )
        affected = result.modified_count
    else:
        result = await openings().delete_many(query)
        affected = result.deleted_count

    await audit.record(
        f"line_item.bulk_{body.action}",
        actor,
        {"projectId": project["_id"]},
        after={"requested": len(body.ids), "affected": affected},
    )
    return {"action": body.action, "requested": len(body.ids), "affected": affected}
