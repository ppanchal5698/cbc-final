"""/adders under /api/reference - manual and Hager list adders.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import HagerAddersUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


def _adder_items(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        r.get("name"): r.get("list_adder")
        for r in payload.get("hager_list_adders", {}).get("items", [])
    }


def _adders() -> dict[str, Any]:
    payload = reflib.load_adders()
    block = payload.get("hager_list_adders", {})
    return {
        "adderTypes": payload.get("adder_types", []),
        "hagerListAdders": {
            "source": block.get("source"),
            "status": block.get("status"),
            "application": block.get("application"),
            "items": block.get("items", []),
        },
        "pending": payload.get("pending", []),
        "rule": payload.get("rule"),
    }


@router.get("/adders")
async def get_adders(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(_adders)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "manual adders data is missing") from exc


@router.patch("/adders")
async def update_adders(body: HagerAddersUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        return await run_sync(_adders)

    before = _adder_items(await run_sync(reflib.load_adders))
    try:
        await run_sync(reflib.update_hager_adders, items=body.items, remove=body.remove)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = _adder_items(await run_sync(reflib.load_adders))
    touched = set(before) | set(after)
    changed = {name: after.get(name) for name in touched if before.get(name) != after.get(name)}
    await audit.record(
        "reference.adders.update",
        actor,
        audit_family("manual_adders"),
        before={name: before.get(name) for name in changed},
        after=changed,
    )
    return await run_sync(_adders)
