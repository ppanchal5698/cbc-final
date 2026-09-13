"""/special-nets under /api/reference - Hager special nets.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import SpecialNetsUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/special-nets")
async def get_special_nets(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(reflib.load_special_nets)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "special nets data is missing") from exc


@router.patch("/special-nets")
async def patch_special_nets(body: SpecialNetsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        return await run_sync(reflib.load_special_nets)
    try:
        after = await run_sync(
            reflib.update_special_net_items,
            items=[i.model_dump(exclude_unset=True) for i in (body.items or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.special_nets.update",
        actor,
        audit_family("hager_special_nets"),
        after={"items": len(body.items or []), "remove": body.remove or []},
    )
    return after
