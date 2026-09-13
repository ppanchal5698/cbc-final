"""POST /api/projects/{code}/vendor-rfqs - open a vendor quote request in draft.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import vendor_rfqs
from cbc.persistence import repos
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VendorRfqCreate(BaseModel):
    rfqNumber: str = Field(min_length=1)
    triggerReason: str
    vendorId: str | None = None
    requestedItems: list[dict[str, Any]] = Field(default_factory=list)
    dueBy: datetime | None = None
    blocksBid: bool = False


@router.post("/vendor-rfqs", status_code=201)
async def create_vendor_rfq(code: str, body: VendorRfqCreate, actor: Actor) -> dict:
    project = await load(code)
    coll = await repos.for_project(vendor_rfqs(), project, actor)
    document = {
        "rfqNumber": body.rfqNumber,
        "bidRequestId": project["_id"],
        "projectId": project["_id"],
        "vendorId": body.vendorId,
        "triggerReason": body.triggerReason,
        "requestedItems": body.requestedItems,
        "status": "draft",
        "statusHistory": [{"status": "draft", "at": _now(), "by": actor}],
        "requestedAt": None,
        "requestedBy": None,
        "dueBy": body.dueBy,
        "blocksBid": body.blocksBid,
    }
    result = await coll.insert(document)
    document["_id"] = result.inserted_id
    return serialise(document)
