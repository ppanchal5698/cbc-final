"""POST /api/projects/{code}/rfis - raise an RFI.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import rfis
from cbc.persistence import repos
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RfiCreate(BaseModel):
    subject: str = Field(min_length=1)
    question: str = Field(min_length=1)
    category: str = "other"
    rfiNumber: str | None = None
    blocksFinalization: bool = False


@router.post("/rfis", status_code=201)
async def create_rfi(code: str, body: RfiCreate, actor: Actor) -> dict:
    project = await load(code)
    coll = await repos.for_project(rfis(), project, actor)
    number = body.rfiNumber or f"RFI-{int(_now().timestamp())}"
    document = {
        "bidRequestId": project["_id"],
        "projectId": project["_id"],
        "rfiNumber": number,
        "subject": body.subject,
        "question": body.question,
        "category": body.category,
        "status": "open",
        "blocksFinalization": body.blocksFinalization,
        "raisedBy": actor,
        "raisedAt": _now(),
        "statusHistory": [{"status": "open", "at": _now(), "by": actor}],
    }
    result = await coll.insert(document)
    document["_id"] = result.inserted_id
    return serialise(document)
