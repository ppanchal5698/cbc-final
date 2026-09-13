"""/finishes under /api/reference - the finish crosswalk.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import FinishesUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/finishes")
async def get_finishes(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(reflib.load_finishes)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "finish crosswalk data is missing") from exc


@router.patch("/finishes")
async def update_finishes(body: FinishesUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.finishes and not body.remove:
        return await run_sync(reflib.load_finishes)

    before = {f.get("us_code") for f in (await run_sync(reflib.load_finishes)).get("finishes", [])}
    try:
        await run_sync(
            reflib.update_finishes,
            finishes=[f.model_dump(exclude_unset=True) for f in (body.finishes or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = {f.get("us_code") for f in (await run_sync(reflib.load_finishes)).get("finishes", [])}
    await audit.record(
        "reference.finishes.update",
        actor,
        audit_family("finishes"),
        before=sorted(before),
        after=sorted(after),
    )
    return await run_sync(reflib.load_finishes)
