"""/special-margins under /api/reference - special customer margins.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import SpecialMarginsUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


def _special_margins(payload: dict[str, Any]) -> dict[str, Any]:
    return {c.get("name"): c.get("margin") for c in payload.get("customers", [])}


def _special() -> dict[str, Any]:
    payload = reflib.load_special_margins()
    return {
        "customers": payload.get("customers", []),
        "rule": payload.get("rule"),
        "status": payload.get("status"),
        "description": payload.get("description"),
    }


@router.get("/special-margins")
async def get_special_margins(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(_special)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "special customer margins data is missing") from exc


@router.patch("/special-margins")
async def update_special_margins(body: SpecialMarginsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.customers and not body.remove:
        return await run_sync(_special)

    before = _special_margins(await run_sync(reflib.load_special_margins))
    try:
        await run_sync(
            reflib.update_special_margins,
            customers=[c.model_dump(exclude_unset=True) for c in (body.customers or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = _special_margins(await run_sync(reflib.load_special_margins))
    touched = set(before) | set(after)
    changed = {name: after.get(name) for name in touched if before.get(name) != after.get(name)}
    await audit.record(
        "reference.special_margins.update",
        actor,
        audit_family("special_customer_margins"),
        before={name: before.get(name) for name in changed},
        after=changed,
    )
    return await run_sync(_special)
