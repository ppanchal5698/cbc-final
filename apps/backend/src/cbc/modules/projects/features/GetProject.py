"""GET /api/projects/{code} - one bid, with the counts the stage bar shows.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure.board import decorate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/{code}")
async def get_project(code: str) -> dict[str, Any]:
    return await decorate(await load(code))
