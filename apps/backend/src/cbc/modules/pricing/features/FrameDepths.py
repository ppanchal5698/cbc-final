"""/frame-depths under /api/reference - wall type to frame depth.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import FrameDepthsUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/frame-depths")
async def get_frame_depths(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(reflib.load_frame_depths)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "frame depths data is missing") from exc


@router.patch("/frame-depths")
async def update_frame_depths(body: FrameDepthsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.wall_types and not body.remove:
        return await run_sync(reflib.load_frame_depths)

    before = {w.get("type") for w in (await run_sync(reflib.load_frame_depths)).get("wall_types", [])}
    try:
        await run_sync(
            reflib.update_frame_depths,
            wall_types=[w.model_dump(exclude_unset=True) for w in (body.wall_types or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = {w.get("type") for w in (await run_sync(reflib.load_frame_depths)).get("wall_types", [])}
    await audit.record(
        "reference.frame_depths.update",
        actor,
        audit_family("frame_depths"),
        before=sorted(before),
        after=sorted(after),
    )
    return await run_sync(reflib.load_frame_depths)
