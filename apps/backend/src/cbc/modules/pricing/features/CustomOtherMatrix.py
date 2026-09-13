"""/custom-other-matrix under /api/reference - the custom/other hardware matrix.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import CustomOtherMatrixReplace
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/custom-other-matrix")
async def get_custom_other_matrix(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(reflib.load_custom_other_matrix)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "custom/other matrix data is missing") from exc


@router.put("/custom-other-matrix")
async def put_custom_other_matrix(
    body: CustomOtherMatrixReplace, actor: AdminActor
) -> dict[str, Any]:
    after = await run_sync(reflib.update_custom_other_matrix, body.data)
    await audit.record(
        "reference.custom_other_matrix.update",
        actor,
        audit_family("custom_other_matrix"),
    )
    return after
