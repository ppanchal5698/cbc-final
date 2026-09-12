"""Ops spend rollup for administrators."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from cbc.http.deps import require_admin
from cbc.services import spend_ops

router = APIRouter(
    prefix="/api/ops",
    tags=["ops"],
    dependencies=[Depends(require_admin)],
)


@router.get("/spend")
async def spend_summary(hours: int = Query(24, ge=1, le=168)) -> dict:
    return await spend_ops.summary(hours=hours)
