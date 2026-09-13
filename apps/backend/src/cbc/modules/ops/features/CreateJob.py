"""POST /api/jobs - enqueue a job. Catalog and price-book jobs need an administrator."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cbc.modules.ops.api import identity, jobs, project_lookup
from cbc.schemas.common import ESTIMATOR_JOB_TYPES, JobType
from cbc.shared.auth import ADMIN_ROLES, Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    type: JobType
    projectId: str | None = None
    payload: dict[str, Any] = {}


@router.post("", status_code=201)
async def create_job(body: JobCreate, actor: Actor) -> dict:
    if body.type == "run_full_pipeline":
        raise HTTPException(
            400,
            "run_full_pipeline is retired. Mark the bid autopilot on upload, or "
            "POST /api/projects/{code}/orchestrate/autopilot to chain domain jobs.",
        )
    if body.type not in ESTIMATOR_JOB_TYPES:
        await _require_admin(actor, body.type)
    project_id = None
    if body.projectId:
        project_id = await project_lookup.project_id(body.projectId)
    if project_id is not None and body.type in jobs.EXCLUSIVE:
        job = await jobs.enqueue_pipeline(
            body.type, project_id, payload=body.payload, actor=actor
        )
    else:
        job = await jobs.enqueue(body.type, project_id, body.payload, actor)
    return serialise(job)


async def _require_admin(actor: str, job_type: str) -> None:
    if await identity.role_of(actor) not in ADMIN_ROLES:
        raise HTTPException(
            403,
            f"{actor} is not permitted to enqueue {job_type!r}. "
            "Catalog and price-book jobs need an administrator.",
        )
