"""POST /api/projects/{code}/quote/lite-kits - a lite kit, louver or glass off National Guard's size tables (NR-1).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import calc, reference_library
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.takeoff import DOOR_HARDWARE
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


class LiteKitCreate(BaseModel):
    table: int = Field(ge=0, description="Which size table: its index in the lite-kit prices")
    width: float = Field(gt=0, le=240, description="Lite width in inches")
    height: float = Field(gt=0, le=240, description="Lite height in inches")
    qty: float = Field(default=1, gt=0)
    group: str | None = Field(default=None, description="The door or set it is for")


def lite_kit_line(prices: dict[str, Any], body: LiteKitCreate, tier: dict[str, Any] | None,
                  lapsed: bool) -> dict[str, Any]:
    """The line's priced fields: the list from the cell the size falls in (an odd or
    fractional size takes the next one up, as the page says), times NGP's multiplier.
    Past the table it is a vendor quote; with no multiplier in force, the estimator's."""
    tables = prices.get("tables") or []
    if body.table >= len(tables):
        raise HTTPException(404, f"no lite-kit table {body.table} ({len(tables)} on file)")
    table = tables[body.table]
    book = Path(str(prices.get("source") or "the National Guard price list")).name
    page = table.get("printed_page") or table.get("pdf_page")
    size = f'{body.width:g}" x {body.height:g}"'
    out: dict[str, Any] = {
        "description": f"{table.get('models') or 'Lite kit'} - {size}".upper(),
        "manufacturer": "National Guard",
        "priceBookVersion": f"{book}, p.{page}",
        "cost": None,
        "priceStatus": "NEEDS_JUDGMENT",
    }
    found = calc.lookup_lite_kit_list_price_from_data({"tables": [table]}, body.width, body.height)
    if found.get("list_price") is None:
        out.update(costSource="VENDOR_RFQ",
                   costSourceDetail=f"{book} p.{page}: {size} is past the printed table - request a quote from National Guard")
        return out
    listed = float(found["list_price"])
    cell = f'{found["width_used"]}" x {found["height_used"]}"'
    where = f"{book} p.{page}: {size} prices at the {cell} cell, list ${listed:.2f}"
    multiplier = (tier or {}).get("multiplier")
    out["listPrice"] = listed
    if not multiplier or lapsed:
        why = "no National Guard multiplier on file" if not multiplier else (
            f"the National Guard multiplier dated {tier.get('effective_date')} is past its review window")
        out.update(costSource="MANUAL", costSourceDetail=f"{where} - {why}: enter the cost")
        return out
    cost = calc.cost_from_list(listed, float(multiplier))["cost"]
    out.update(
        cost=cost, costSource="LIST_X_MULTIPLIER", priceStatus="PRICED",
        costSourceDetail=f"{where} x NGP {float(multiplier):g} -> ${cost:.2f}",
        multiplier=float(multiplier), multiplierTier=tier.get("tier") or "all",
        multiplierEffectiveDate=tier.get("effective_date"),
    )
    return out


@router.post("/lite-kits", status_code=201)
async def add_lite_kit(code: str, body: LiteKitCreate, actor: Actor) -> dict:
    project = await load(code)
    prices, tiers = await asyncio.gather(asyncio.to_thread(reference_library.load_lite_kit_prices),
                                         asyncio.to_thread(reference_library.load_vendor_tiers))
    tier = next((v for v in tiers.get("vendors") or [] if v.get("key") == "national_guard"), None)
    lapsed = bool(tier) and await asyncio.to_thread(reference_library.sheet_lapsed, tier.get("effective_date"))
    priced = lite_kit_line(prices, body, tier, lapsed)
    now = datetime.now(timezone.utc)
    document = {
        "sell": None, "extended": None, "margin": None,
        **priced,
        "division": DOOR_HARDWARE,
        "group": body.group,
        "qty": body.qty,
        "unit": "EA",
        "pricedAt": now.isoformat(),
        "projectId": project["_id"],
        "lineKey": f"hand-{ObjectId()}",
        "addedByHand": True,
        "marginOverridden": False,
        "flags": [],
        "createdAt": now,
    }
    result = await estimate_lines().insert_one(document)
    await audit.record("quote.line_added", actor, {"projectId": project["_id"], "quoteLineId": result.inserted_id},
                       after=priced["description"], note=priced["costSourceDetail"])
    totals = await quote_service.persist(project)
    return {"line": serialise(await estimate_lines().find_one({"_id": result.inserted_id})), "totals": totals}
