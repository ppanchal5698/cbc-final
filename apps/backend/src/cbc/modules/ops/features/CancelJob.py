"""POST /api/jobs/{job_id}/cancel - stop a queued or running job."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, actor: Actor) -> dict:
    job = await jobs_collection().find_one({"_id": oid(job_id)})
    if not job:
        raise HTTPException(404, "job not found")
    if job["status"] not in ("queued", "running"):
        raise HTTPException(409, f"job is already {job['status']}")

    await jobs_collection().update_one(
        {"_id": job["_id"]},
        {
            "$set": {
                "status": "cancelled",
                "cancelledAt": datetime.now(timezone.utc),
                "cancelledBy": actor,
            }
        },
    )
    await audit.record(
        "job.cancel",
        actor,
        {"jobId": job["_id"], "projectId": job.get("projectId")},
    )
    return serialise(await jobs_collection().find_one({"_id": job["_id"]}))
