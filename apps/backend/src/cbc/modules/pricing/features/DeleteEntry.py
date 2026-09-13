"""DELETE /api/reference/{family}/entries/{key} - remove one entry from any family.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib, reference_store
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.delete("/{family}/entries/{key}")
async def delete_entry(family: str, key: str, actor: AdminActor) -> dict[str, Any]:
    if family not in reference_store.FAMILIES:
        raise HTTPException(404, f"unknown family {family!r}")
    try:
        after = await run_sync(reflib.delete_family_entry, family, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.entry.delete",
        actor,
        audit_family(family),
        after={"key": key},
    )
    return after
