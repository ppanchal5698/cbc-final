"""POST /api/projects/{code}/line-items - add what the drawings do not carry; confirmed on arrival.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from cbc.modules.extraction.api import feedback
from cbc.modules.extraction.domain.openings import LineItemCreate
from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.persistence import repos
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", status_code=201)
async def add_line_item(code: str, body: LineItemCreate, actor: Actor) -> dict:
    """Add something the drawings do not carry. Confirmed on arrival - a human typed it."""
    project = await load(code)
    scoped = await repos.for_project(openings(), project, actor)

    payload = body.model_dump(exclude_none=True)
    mark = payload.get("mark") or payload.get("doorNumber")
    document = {
        **payload,
        "projectId": project["_id"],
        "bidRequestId": project["_id"],
        "mark": mark,
        "doorNumber": str(mark) if mark else None,
        "status": "by_hand",
        "addedByHand": True,
        "confidence": 1.0,
        "flags": [],
        "evidence": {"note": f"Added by hand by {actor}"},
        "confirmedBy": actor,
        "confirmedAt": _now(),
    }
    result = await scoped.insert(document)
    document["_id"] = result.inserted_id

    await audit.record(
        "line_item.add_by_hand",
        actor,
        {"projectId": project["_id"], "lineItemId": result.inserted_id},
        after=body.description,
    )
    await feedback.record(
        bid_request_id=project["_id"],
        event_type="lineAdded",
        actor=actor,
        opening_id=result.inserted_id,
        corrected={"description": body.description, "mark": mark},
    )
    return serialise(document)
