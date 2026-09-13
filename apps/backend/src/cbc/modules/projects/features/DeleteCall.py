"""DELETE /api/projects/{code}/calls/{call_id} - remove a logged call, note or RFI.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure.collections import calls
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/projects/{code}/calls", tags=["calls"])


@router.delete("/{call_id}", status_code=204, response_class=Response)
async def delete_call(code: str, call_id: str, actor: Actor) -> Response:
    project = await load(code)
    entry = await calls().find_one({"_id": oid(call_id), "projectId": project["_id"]})
    if not entry:
        raise HTTPException(404, "note not found")

    await calls().delete_one({"_id": entry["_id"]})
    await audit.record(
        "call.delete",
        actor,
        {"projectId": project["_id"], "callId": entry["_id"]},
        before=entry.get("text", "")[:200],
    )
    return Response(status_code=204)
