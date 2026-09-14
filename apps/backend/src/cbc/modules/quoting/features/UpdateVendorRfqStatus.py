"""PATCH /api/projects/{code}/vendor-rfqs/{rfq_id} - move an RFQ along its states.

Marking one received records what the vendor quoted, each price against the quote
line it prices. Marking it applied writes those prices onto the lines as their
cost - source VENDOR_RFQ, detail naming the RFQ - and reprices the quote, so the
third cost path (FR-16) ends in a priced line rather than a status.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.rfqs_and_rfis import RFQ_TRANSITIONS
from cbc.modules.quoting.infrastructure.collections import estimate_lines, vendor_rfqs
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class QuotedPrice(BaseModel):
    estimateLineId: str
    amount: float = Field(ge=0)
    leadTimeDays: int | None = Field(default=None, ge=0)
    validUntil: datetime | None = None
    notes: str | None = None


class RfqStatusUpdate(BaseModel):
    status: str
    # Required when the status is `received`: what the vendor quoted, line by line.
    quotedPrices: list[QuotedPrice] | None = None


async def _lines_of(project: dict[str, Any], ids: list[str]) -> dict[str, dict[str, Any]]:
    """The bid's quote lines among `ids`, by id. An id on another bid is simply absent."""
    rows = await estimate_lines().find(
        {"projectId": project["_id"], "_id": {"$in": [oid(line_id) for line_id in ids]}}
    ).to_list(len(ids))
    return {str(row["_id"]): row for row in rows}


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

    now = _now()
    changes: dict[str, Any] = {"status": body.status, "updatedAt": now}

    if body.status == "received":
        if not body.quotedPrices:
            raise HTTPException(400, "record at least one quoted price, against the quote line it prices")
        wanted = {price.estimateLineId for price in body.quotedPrices}
        unknown = sorted(wanted - set(await _lines_of(project, sorted(wanted))))
        if unknown:
            raise HTTPException(400, f"not quote lines on this bid: {', '.join(unknown)}")
        changes["quotedPrices"] = [
            {**price.model_dump(), "currency": "USD"} for price in body.quotedPrices
        ]
        changes["respondedAt"] = now

    applied: list[Any] = []
    if body.status == "applied":
        prices = [
            price
            for price in row.get("quotedPrices") or []
            if price.get("estimateLineId") and price.get("amount") is not None
        ]
        if not prices:
            raise HTTPException(400, "this RFQ has no quoted price to apply")
        lines = await _lines_of(project, [price["estimateLineId"] for price in prices])
        detail = f"Vendor RFQ {row['rfqNumber']}" + (f" ({row['vendorId']})" if row.get("vendorId") else "")
        for price in prices:
            line = lines.get(price["estimateLineId"])
            if line is None:  # deleted since the price came back
                continue
            after = {"cost": float(price["amount"]), "costSource": "VENDOR_RFQ", "costSourceDetail": detail}
            before = {key: line.get(key) for key in after}
            await estimate_lines().update_one(
                {"_id": line["_id"]},
                {
                    "$set": {**after, "vendorRfqId": row["_id"], "updatedAt": now},
                    "$push": {"overrides": {"at": now, "by": actor, "before": before, "after": after, "reason": detail}},
                },
            )
            await audit.record(
                "quote.vendor_price_applied",
                actor,
                {"projectId": project["_id"], "quoteLineId": line["_id"], "vendorRfqId": row["_id"]},
                before=before,
                after=after,
                note=detail,
            )
            applied.append(line["_id"])
        if not applied:
            raise HTTPException(400, "every line this RFQ priced has since been deleted")

    await vendor_rfqs().update_one(
        {"_id": row["_id"]},
        {"$set": changes, "$push": {"statusHistory": {"status": body.status, "at": now, "by": actor}}},
    )
    if applied:
        await quote_service.persist(project)
    row.update(changes)
    return serialise(row)
