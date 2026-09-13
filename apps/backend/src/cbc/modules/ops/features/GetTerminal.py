"""GET /api/jobs/{job_id}/terminal - the whole recording so far, for replaying a run."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection
from cbc.shared.config import settings
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/jobs/{job_id}/terminal", tags=["terminal"])


async def _job(job_id: str) -> dict:
    job = await jobs_collection().find_one({"_id": oid(job_id)})
    if not job:
        raise HTTPException(404, "job not found")
    return job


def _recording_of(job: dict) -> Path | None:
    relative = job.get("recording")
    if not relative:
        return None
    # Never let a stored path escape the project tree.
    path = (settings.repo_root / relative).resolve()
    if not str(path).startswith(str(settings.repo_root.resolve())):
        raise HTTPException(400, "recording path is outside the project tree")
    return path


@router.get("")
async def get_terminal(job_id: str) -> dict:
    """The whole recording so far, for replaying a finished run."""
    job = await _job(job_id)
    path = _recording_of(job)

    if path is None or not path.exists():
        return {
            "jobId": job_id,
            "status": job.get("status"),
            "available": False,
            "reason": (
                "Detailed logs aren't available for this run."
                if job.get("status") in ("done", "failed", "cancelled")
                else "Nothing has been written yet."
            ),
            "data": "",
        }

    payload = await asyncio.to_thread(path.read_bytes)
    return {
        "jobId": job_id,
        "status": job.get("status"),
        "available": True,
        "bytes": len(payload),
        # base64 so the escape sequences survive JSON intact.
        "data": base64.b64encode(payload).decode("ascii"),
    }
