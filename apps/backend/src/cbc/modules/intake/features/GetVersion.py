"""GET /api/projects/{code}/versions/{version} - one version, snapshot included.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.projects.api.lookup import load
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


@router.get("/versions/{version}")
async def get_version(code: str, version: int) -> dict[str, Any]:
    project = await load(code)
    found = await versions().find_one({"projectId": project["_id"], "version": version})
    if not found:
        raise HTTPException(404, f"version {version} not found")
    return serialise(found)
