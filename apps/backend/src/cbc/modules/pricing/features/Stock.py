"""/stock/{vendor} under /api/reference - a vendor's stock list.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import StockUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/stock/{vendor}")
async def get_stock(vendor: str, actor: Actor) -> dict[str, Any]:
    payload = await run_sync(reflib.load_stock_list, vendor)
    if payload is None:
        raise HTTPException(404, f"no stock list for vendor {vendor!r}")
    return payload


@router.patch("/stock/{vendor}")
async def patch_stock(vendor: str, body: StockUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        payload = await run_sync(reflib.load_stock_list, vendor)
        if payload is None:
            raise HTTPException(404, f"no stock list for vendor {vendor!r}")
        return payload
    try:
        after = await run_sync(
            reflib.update_stock_items,
            vendor,
            items=[i.model_dump(exclude_unset=True) for i in (body.items or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.stock.update",
        actor,
        audit_family(reflib.stock_family_for(vendor) or "stock"),
        after={"vendor": vendor, "items": len(body.items or []), "remove": body.remove or []},
    )
    return after
