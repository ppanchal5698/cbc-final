"""FR-16 / Phase 5 / FR-12 operational collection routers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cbc.db import db
from cbc.shared.mongo import oid, serialise
from cbc.shared.auth import Actor
from cbc.modules.projects.api.lookup import load
from cbc.persistence import repos
from cbc.schemas.operational import RFQ_TRANSITIONS

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


class RfqStatusUpdate(BaseModel):
    status: str


class RfiCreate(BaseModel):
    subject: str = Field(min_length=1)
    question: str = Field(min_length=1)
    category: str = "other"
    rfiNumber: str | None = None
    blocksFinalization: bool = False


@router.get("/vendor-rfqs")
async def list_vendor_rfqs(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await db.vendor_rfqs.find({"bidRequestId": project["_id"]}).to_list(500)
    return {"vendorRfqs": serialise(rows)}


@router.post("/vendor-rfqs", status_code=201)
async def create_vendor_rfq(code: str, body: VendorRfqCreate, actor: Actor) -> dict:
    project = await load(code)
    coll = await repos.for_project(db.vendor_rfqs, project, actor)
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


@router.patch("/vendor-rfqs/{rfq_id}")
async def update_vendor_rfq_status(
    code: str, rfq_id: str, body: RfqStatusUpdate, actor: Actor
) -> dict:
    project = await load(code)
    row = await db.vendor_rfqs.find_one({"_id": oid(rfq_id), "bidRequestId": project["_id"]})
    if not row:
        raise HTTPException(404, "vendor RFQ not found")
    current = row.get("status") or "draft"
    allowed = RFQ_TRANSITIONS.get(current, ())
    if body.status not in allowed:
        raise HTTPException(400, f"cannot move RFQ from {current!r} to {body.status!r}")
    await db.vendor_rfqs.update_one(
        {"_id": row["_id"]},
        {
            "$set": {"status": body.status, "updatedAt": _now()},
            "$push": {"statusHistory": {"status": body.status, "at": _now(), "by": actor}},
        },
    )
    if body.status == "applied":
        await db.quote_lines.update_many(
            {"projectId": project["_id"], "vendorRfqId": row["_id"]},
            {"$set": {"costSource": "VENDOR_RFQ", "updatedAt": _now()}},
        )
    row["status"] = body.status
    return serialise(row)


@router.get("/rfis")
async def list_rfis(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await db.rfis.find({"bidRequestId": project["_id"]}).to_list(500)
    return {"rfis": serialise(rows)}


@router.post("/rfis", status_code=201)
async def create_rfi(code: str, body: RfiCreate, actor: Actor) -> dict:
    project = await load(code)
    coll = await repos.for_project(db.rfis, project, actor)
    number = body.rfiNumber or f"RFI-{int(_now().timestamp())}"
    document = {
        "bidRequestId": project["_id"],
        "projectId": project["_id"],
        "rfiNumber": number,
        "subject": body.subject,
        "question": body.question,
        "category": body.category,
        "status": "open",
        "blocksFinalization": body.blocksFinalization,
        "raisedBy": actor,
        "raisedAt": _now(),
        "statusHistory": [{"status": "open", "at": _now(), "by": actor}],
    }
    result = await coll.insert(document)
    document["_id"] = result.inserted_id
    return serialise(document)
