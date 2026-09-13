"""PATCH /api/projects/{code}/line-items/{item_id} - correct an opening; each corrected field is recorded.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.extraction.api import feedback
from cbc.modules.extraction.domain.openings import LineItemUpdate
from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("/{item_id}")
async def update_line_item(
    code: str, item_id: str, body: LineItemUpdate, actor: Actor
) -> dict:
    project = await load(code)
    item = await openings().find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")

    changes = body.model_dump(exclude_none=True)
    if not changes:
        return serialise(item)

    edit = {
        "at": _now(),
        "by": actor,
        "before": {key: item.get(key) for key in changes},
        "after": changes,
    }
    await openings().update_one(
        {"_id": item["_id"]},
        {"$set": {**changes, "updatedAt": _now()}, "$push": {"edits": edit}},
    )
    await audit.record(
        "line_item.edit",
        actor,
        {"projectId": project["_id"], "lineItemId": item["_id"]},
        before=edit["before"],
        after=changes,
    )
    await feedback.record_edits(
        bid_request_id=project["_id"],
        actor=actor,
        opening_id=item["_id"],
        before=edit["before"],
        changes=changes,
    )
    return serialise(await openings().find_one({"_id": item["_id"]}))
