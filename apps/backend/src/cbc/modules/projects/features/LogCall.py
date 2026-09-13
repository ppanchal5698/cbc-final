"""POST /api/projects/{code}/calls - log a call, note or RFI against a bid.

Phase 5 of the CBC process is judgment: reuse, direct equals, and raising RFIs
before finalising. Those conversations happen on the phone and then evaporate.
Logging them against the estimate is how they survive - the note travels with the
bid, and an estimator months later can see why a line reads the way it does.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure.collections import calls
from cbc.schemas.common import CallKind
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/calls", tags=["calls"])


class CallCreate(BaseModel):
    kind: CallKind = "call"
    text: str = Field(min_length=1, max_length=4000)
    org: str | None = Field(default=None, description="Who it was with - GC, architect, vendor")
    ref: str | None = Field(default=None, description="The stage or line it was logged against")


@router.post("", status_code=201)
async def log_call(code: str, body: CallCreate, actor: Actor) -> dict:
    project = await load(code)

    document = {
        **body.model_dump(exclude_none=True),
        "projectId": project["_id"],
        "who": actor,
        "createdAt": datetime.now(timezone.utc),
    }
    result = await calls().insert_one(document)
    document["_id"] = result.inserted_id

    await audit.record(
        f"call.{body.kind}",
        actor,
        {"projectId": project["_id"], "callId": result.inserted_id},
        after=body.text[:200],
        note=body.ref,
    )
    return serialise(document)
