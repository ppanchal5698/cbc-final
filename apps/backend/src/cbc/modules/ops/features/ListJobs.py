"""GET /api/jobs - recent jobs, optionally for one bid or only its active pipeline job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import jobs, project_lookup
from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    project: str | None = None,
    status: str | None = None,
    limit: int = 25,
    pipeline_active: bool = False,
) -> dict:
    query: dict = {}
    project_id = None
    if project:
        project_id = await project_lookup.project_id(project)
        query["projectId"] = project_id
    if pipeline_active:
        if project_id is None:
            raise HTTPException(400, "project is required when pipeline_active is set")
        active = await jobs.active_pipeline_job(project_id)
        return {
            "jobs": serialise([active]) if active else [],
            "active": await jobs.active_count(),
        }
    if status:
        query["status"] = status

    found = await jobs_collection().find(query).sort("createdAt", -1).to_list(min(limit, 100))
    return {"jobs": serialise(found), "active": await jobs.active_count()}
