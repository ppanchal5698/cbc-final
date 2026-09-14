"""PATCH /api/projects/{code}/rfis/{rfi_id} - move an RFI along its states; answering records the answer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.domain.rfqs_and_rfis import RFI_TRANSITIONS
from cbc.modules.quoting.infrastructure.collections import rfis
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RfiStatusUpdate(BaseModel):
    status: str
    # Required when the status is `answered`.
    answer: str | None = None


@router.patch("/rfis/{rfi_id}")
async def update_rfi_status(code: str, rfi_id: str, body: RfiStatusUpdate, actor: Actor) -> dict:
    project = await load(code)
    row = await rfis().find_one({"_id": oid(rfi_id), "bidRequestId": project["_id"]})
    if not row:
        raise HTTPException(404, "RFI not found")
    current = row.get("status") or "open"
    if body.status not in RFI_TRANSITIONS.get(current, ()):
        raise HTTPException(400, f"cannot move RFI from {current!r} to {body.status!r}")

    now = _now()
    changes: dict[str, Any] = {"status": body.status, "updatedAt": now}
    if body.status == "answered":
        answer = (body.answer or "").strip()
        if not answer:
            raise HTTPException(400, "record the answer the RFI received")
        changes.update(answer=answer, answeredAt=now)

    await rfis().update_one(
        {"_id": row["_id"]},
        {"$set": changes, "$push": {"statusHistory": {"status": body.status, "at": now, "by": actor}}},
    )
    row.update(changes)
    return serialise(row)
