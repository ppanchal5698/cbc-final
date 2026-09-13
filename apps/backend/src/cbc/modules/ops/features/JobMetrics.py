"""GET /api/jobs/metrics - queue depth, throughput and failure rate."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.ops.api import jobs
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/metrics")
async def job_metrics(hours: int = 24) -> dict:
    """Queue depth, throughput and failure rate.

    Declared before `/{job_id}`: FastAPI matches in declaration order, so the
    other way round this route is a job whose id is the word "metrics".
    """
    return serialise(await jobs.metrics(max(1, min(hours, 24 * 30))))
