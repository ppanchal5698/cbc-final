"""GET /api/projects/{code}/versions - a bid's versions, newest first, without their snapshots.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.intake.domain.versions import PENDING_NOTE
from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.projects.api.lookup import load
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


@router.get("/versions")
async def list_versions(code: str) -> dict[str, Any]:
    project = await load(code)
    found = (
        await versions().find({"projectId": project["_id"]}, {"snapshot": 0})
        .sort("version", -1)
        .to_list(50)
    )
    unreconciled = await versions().count_documents(
        {"projectId": project["_id"], "reconciled": {"$ne": True}}
    )
    return {
        "versions": serialise(found),
        "current": project.get("version", 1),
        "unreconciled": unreconciled,
        "pending": PENDING_NOTE,
    }
