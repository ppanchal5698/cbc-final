"""GET /api/projects/{code}/rfis - the questions raised on a bid before finalising.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import rfis
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


@router.get("/rfis")
async def list_rfis(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await rfis().find({"bidRequestId": project["_id"]}).to_list(500)
    return {"rfis": serialise(rows)}
