"""POST /api/projects/{code}/calls/{call_id}/resolve - close an answered RFI.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure.collections import calls
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/calls", tags=["calls"])


@router.post("/{call_id}/resolve")
async def resolve_rfi(code: str, call_id: str, actor: Actor) -> dict:
    """Close an RFI once the architect or GC has answered."""
    project = await load(code)
    entry = await calls().find_one({"_id": oid(call_id), "projectId": project["_id"]})
    if not entry:
        raise HTTPException(404, "note not found")
    if entry.get("kind") != "rfi":
        raise HTTPException(400, "only an RFI can be resolved")

    await calls().update_one(
        {"_id": entry["_id"]},
        {"$set": {"resolvedAt": datetime.now(timezone.utc), "resolvedBy": actor}},
    )
    await audit.record(
        "call.rfi_resolved", actor, {"projectId": project["_id"], "callId": entry["_id"]}
    )
    return serialise(await calls().find_one({"_id": entry["_id"]}))
