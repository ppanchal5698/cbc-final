"""/vendor-tiers under /api/reference - vendor multiplier tiers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import VendorCategoriesUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/vendor-tiers")
async def get_vendor_tiers(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(reflib.load_vendor_tiers)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "vendor tiers data is missing") from exc


@router.patch("/vendor-tiers")
async def patch_vendor_tiers(body: VendorCategoriesUpdate, actor: AdminActor) -> dict[str, Any]:
    try:
        after = await run_sync(reflib.update_vendor_categories, body.vendor, body.categories)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.vendor_tiers.update",
        actor,
        audit_family("vendor_tiers"),
        after={"vendor": body.vendor, "categories": body.categories},
    )
    return after
