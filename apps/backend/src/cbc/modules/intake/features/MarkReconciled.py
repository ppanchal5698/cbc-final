"""POST /api/projects/{code}/versions/{version}/reconcile - record that a version's differences were reviewed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.persistence import versioning
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/versions/{version}/reconcile")
async def mark_reconciled(code: str, version: int, actor: Actor) -> dict:
    project = await load(code)
    stored = await versions().find_one({"projectId": project["_id"], "version": version})
    if stored is None:
        raise HTTPException(404, f"version {version} not found")
    try:
        versioning.guard_writable(stored)
    except versioning.VersionLocked as exc:
        # §3.26: a sealed version must never be written again. This handler used
        # to reach any version, including ones superseded months earlier.
        raise HTTPException(409, str(exc)) from exc

    result = await versions().update_one(
        {"projectId": project["_id"], "version": version, "lockedAt": None},
        {"$set": {"reconciled": True, "reconciledBy": actor, "reconciledAt": _now()}},
    )
    if not result.matched_count:
        raise HTTPException(409, f"version {version} was sealed while reconciling")

    await audit.record(
        "version.reconciled", actor, {"projectId": project["_id"]}, after={"version": version}
    )
    return {"version": version, "reconciled": True, "by": actor}
