"""POST /api/projects/{code}/addenda, PATCH /api/projects/{code}/addenda/{number} - the addendum log (FR-14).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.projects.api import bids
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.domain.addenda import AddendumCreate, AddendumUpdate
from cbc.modules.projects.infrastructure.collections import bid_requests
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects", tags=["projects"])

_DATES = ("issuedOn", "newBidDue")


def _stored(fields: dict[str, Any]) -> dict[str, Any]:
    """Dates as the bid stores `bidDue`: midnight UTC, which Mongo can hold."""
    return {
        key: datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        if key in _DATES and isinstance(value, date) else value
        for key, value in fields.items()
    }


async def _move_bid_date(project: dict[str, Any], due: datetime, number: int, actor: str) -> None:
    """An addendum that moves the bid date moves the bid's - it is the new date."""
    await bid_requests().update_one(
        {"_id": project["_id"]}, {"$set": {"bidDue": due, "updatedAt": datetime.now(timezone.utc)}}
    )
    await audit.record("project.bid_due_moved", actor, {"projectId": project["_id"]},
                       before=project.get("bidDue"), after=due, note=f"addendum {number}")


@router.post("/{code}/addenda", status_code=201)
async def log_addendum(code: str, body: AddendumCreate, actor: Actor) -> dict:
    project = await load(code)
    entry = _stored(body.model_dump(exclude_none=True))
    if entry.get("newBidDue"):
        entry["previousBidDue"] = project.get("bidDue")
    try:
        stored = await bids.log_addendum(project["_id"], entry, by=actor)
    except bids.AddendumExists as exc:
        raise HTTPException(409, str(exc)) from exc
    if stored.get("newBidDue"):
        await _move_bid_date(project, stored["newBidDue"], stored["number"], actor)
    await audit.record("addendum.log", actor, {"projectId": project["_id"]}, after=serialise(stored))
    return serialise(stored)


@router.patch("/{code}/addenda/{number}")
async def update_addendum(code: str, number: int, body: AddendumUpdate, actor: Actor) -> dict:
    project = await load(code)
    current = next((a for a in project.get("addenda") or [] if a.get("number") == number), None)
    if current is None:
        raise HTTPException(404, f"addendum {number} is not logged on this bid")
    changes = _stored(body.model_dump(exclude_unset=True))
    moved = changes.get("newBidDue") and changes["newBidDue"] != current.get("newBidDue")
    if moved:
        changes["previousBidDue"] = project.get("bidDue")
    if changes:
        await bid_requests().update_one(
            {"_id": project["_id"], "addenda.number": number},
            {"$set": {f"addenda.$.{key}": value for key, value in changes.items()}},
        )
    if moved:
        await _move_bid_date(project, changes["newBidDue"], number, actor)
    updated = {**current, **changes}
    await audit.record("addendum.update", actor, {"projectId": project["_id"]},
                       before=serialise(current), after=serialise(updated))
    return serialise(updated)
