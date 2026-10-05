"""GET /api/memory - what the graph holds; GET /api/memory/projects/{code}/similar."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from cbc.modules.memory.api import recall
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import require_admin

admin = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_admin)])
router = APIRouter(prefix="/api/memory", tags=["memory"])


@admin.get("")
async def memory_summary() -> dict[str, Any]:
    return await recall.summary()


@router.get("/projects/{code}/similar")
async def similar(code: str) -> dict[str, Any]:
    """Approved bids most like this one - for any signed-in estimator."""
    project = await load(code)
    return {"bids": await recall.similar_bids(project)}
