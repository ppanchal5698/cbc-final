"""POST /api/jobs/{job_id}/retry - re-queue a dead or failed job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import jobs
from cbc.shared import events
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
    # The bid's saga is projects' to move. ops says what happened; projects puts the
    # bid back in the requeued job's starting state before this responds.
    await events.publish(jobs.JOB_REQUEUED, job=job)
    return serialise(job)
