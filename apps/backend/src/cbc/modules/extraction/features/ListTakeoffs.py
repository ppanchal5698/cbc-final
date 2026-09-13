"""GET /api/projects/{code}/takeoffs - FRP geometry recorded against a bid (FR-12).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.infrastructure.collections import takeoffs
from cbc.modules.projects.api.lookup import load
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


@router.get("/takeoffs")
async def list_takeoffs(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await takeoffs().find({"bidRequestId": project["_id"]}).to_list(100)
    return {"takeoffs": serialise(rows)}
