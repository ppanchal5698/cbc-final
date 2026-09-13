"""POST /api/jobs/{job_id}/retry - re-queue a dead or failed job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import jobs
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, actor: Actor) -> dict:
    try:
        job = await jobs.retry(oid(job_id), actor)
    except KeyError:
        raise HTTPException(404, "job not found") from None
    except jobs.JobNotRetryable as exc:
        raise HTTPException(409, f"job cannot be retried ({exc.status})") from None
    except jobs.PipelineJobActive as exc:
        raise HTTPException(
            409,
            detail={
                "message": "A Claude run is already in progress for this bid",
                "activeJob": serialise(exc.active),
            },
        ) from None
    # ponytail: writes the bid's chainState directly; becomes a JobRequeued event
    # the projects module handles once it owns chainState (step 3.4).
    from cbc.services import chain

    start = chain.START_STATE.get(job.get("type") or "")
    if start and job.get("projectId") is not None:
        await chain.set_state(job["projectId"], start, detail="Requeued from the dead-letter queue.")
    return serialise(job)
