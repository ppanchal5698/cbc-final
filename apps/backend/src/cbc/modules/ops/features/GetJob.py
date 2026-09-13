"""GET /api/jobs/{job_id} - one job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    job = await jobs_collection().find_one({"_id": oid(job_id)})
    if not job:
        raise HTTPException(404, "job not found")
    return serialise(job)
