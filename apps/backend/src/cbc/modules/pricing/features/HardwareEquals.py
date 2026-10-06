"""/hardware-equals under /api/reference - the equal CBC quotes for an Allegion part.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import HardwareEqualsUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/hardware-equals")
async def get_hardware_equals(actor: Actor) -> dict[str, Any]:
    return await run_sync(reflib.load_hardware_equals)


@router.patch("/hardware-equals")
async def patch_hardware_equals(body: HardwareEqualsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        return await run_sync(reflib.load_hardware_equals)
    items = [{**item.model_dump(exclude_none=True), "named_by": actor} for item in body.items or []]
    try:
        after = await run_sync(reflib.update_hardware_equals, items=items, remove=body.remove, actor=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record("reference.hardware_equals.update", actor, audit_family("hardware_equals"),
                       after={"items": items, "remove": body.remove or []})
    return after
