"""POST /api/projects/{code}/versions - freeze the bid as a version, optionally queueing an addendum pass.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.intake.domain.versions import PENDING_NOTE
from cbc.modules.intake.domain.versions import VersionCreate
from cbc.modules.intake.infrastructure.snapshot import snapshot
from cbc.modules.ops.api.jobs import enqueue_pipeline, reserve
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


@router.post("/versions", status_code=201)
async def create_version(code: str, body: VersionCreate, actor: Actor) -> dict:
    project = await load(code)

    # Before the snapshot, not after it: a 409 raised from the enqueue below used
    # to leave a frozen version behind that no job would ever read.
    superseded = await reserve(project["_id"], "ingest_addendum") if body.documentId else None

    document = await snapshot(project, body.reason, actor)

    job = None
    if body.documentId:
        job = await enqueue_pipeline(
            "ingest_addendum",
            project["_id"],
            payload={
                "documentId": body.documentId,
                "version": document["version"],
                "reason": body.reason,
            },
            actor=actor,
        )

    return {
        "version": serialise({k: v for k, v in document.items() if k != "snapshot"}),
        "job": serialise(job) if job else None,
        "superseded": serialise(superseded) if superseded else None,
        "pending": PENDING_NOTE,
    }
