"""GET /api/projects - the board: bids newest first, by stage or a search.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query

from cbc.modules.projects.infrastructure.board import decorate_many
from cbc.modules.projects.infrastructure.collections import bid_requests

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def list_projects(
    stage: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if stage:
        query["stage"] = stage
    if q:
        needle = re.escape(q)  # user input, not a pattern
        query["$or"] = [
            {"name": {"$regex": needle, "$options": "i"}},
            {"code": {"$regex": needle, "$options": "i"}},
            {"gc": {"$regex": needle, "$options": "i"}},
            {"brand": {"$regex": needle, "$options": "i"}},
        ]

    projects = await bid_requests().find(query).sort("createdAt", -1).to_list(length=limit)
    return {"projects": await decorate_many(projects)}
