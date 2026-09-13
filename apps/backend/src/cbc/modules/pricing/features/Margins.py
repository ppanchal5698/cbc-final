"""/margins under /api/reference - margin framework.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.core import calc
from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import MarginFrameworkUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


def _framework() -> dict[str, Any]:
    payload = reflib.load_margins()
    return {
        "bands": payload.get("bands", []),
        "accessoriesDerived": payload.get("accessories_derived"),
        "formula": payload.get("formula"),
        "overridable": payload.get("overridable"),
        "governance": payload.get("governance"),
        "source": payload.get("source"),
        "effective": calc.bands(),
    }


@router.get("/margins")
async def get_margins(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(_framework)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "margin framework is missing") from exc


@router.patch("/margins")
async def update_margins(body: MarginFrameworkUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.bands and body.accessories is None:
        return await run_sync(_framework)

    before = await run_sync(reflib.load_margins)
    before_bands = {b.get("key"): b.get("margin") for b in before.get("bands", [])}
    before_bands["accessories"] = before.get("accessories_derived")

    try:
        await run_sync(reflib.update_margins, bands=body.bands, accessories=body.accessories)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = await run_sync(reflib.load_margins)
    after_bands = {b.get("key"): b.get("margin") for b in after.get("bands", [])}
    after_bands["accessories"] = after.get("accessories_derived")

    changed = {
        key: value for key, value in after_bands.items() if before_bands.get(key) != value
    }
    await audit.record(
        "reference.margins.update",
        actor,
        audit_family("margins"),
        before={key: before_bands.get(key) for key in changed},
        after=changed,
    )
    return await run_sync(_framework)
