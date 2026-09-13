"""PATCH /api/projects/{code}/vendor-rfqs/{rfq_id} - move an RFQ along its states; applied marks its lines.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import estimate_lines, vendor_rfqs
from cbc.schemas.operational import RFQ_TRANSITIONS  # ponytail: the collection-spec module dissolves in Phase 4
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RfqStatusUpdate(BaseModel):
    status: str


@router.patch("/vendor-rfqs/{rfq_id}")
async def update_vendor_rfq_status(
    code: str, rfq_id: str, body: RfqStatusUpdate, actor: Actor
) -> dict:
    project = await load(code)
    row = await vendor_rfqs().find_one({"_id": oid(rfq_id), "bidRequestId": project["_id"]})
    if not row:
        raise HTTPException(404, "vendor RFQ not found")
    current = row.get("status") or "draft"
    allowed = RFQ_TRANSITIONS.get(current, ())
    if body.status not in allowed:
        raise HTTPException(400, f"cannot move RFQ from {current!r} to {body.status!r}")
    await vendor_rfqs().update_one(
        {"_id": row["_id"]},
        {
            "$set": {"status": body.status, "updatedAt": _now()},
            "$push": {"statusHistory": {"status": body.status, "at": _now(), "by": actor}},
        },
    )
    if body.status == "applied":
        await estimate_lines().update_many(
            {"projectId": project["_id"], "vendorRfqId": row["_id"]},
            {"$set": {"costSource": "VENDOR_RFQ", "updatedAt": _now()}},
        )
    row["status"] = body.status
    return serialise(row)
