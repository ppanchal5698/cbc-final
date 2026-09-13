"""/frp-constants under /api/reference - FRP conversion constants.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import FrpConstantsUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/frp-constants")
async def get_frp_constants(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(reflib.load_frp_constants)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "FRP constants data is missing") from exc


@router.patch("/frp-constants")
async def update_frp_constants(body: FrpConstantsUpdate, actor: AdminActor) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    if not values:
        return await run_sync(reflib.load_frp_constants)

    before = await run_sync(reflib.load_frp_constants)
    try:
        after = await run_sync(reflib.update_frp_constants, values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    await audit.record(
        "reference.frp_constants.update",
        actor,
        audit_family("frp_constants"),
        before={field: before.get(field) for field in values} | {"status": before.get("status")},
        after={field: after.get(field) for field in values} | {"status": after.get("status")},
    )
    return after
