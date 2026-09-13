"""Shared helpers for one-Claude-session-per-bid enforcement in API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from cbc.db import db
from cbc.shared.mongo import serialise
from cbc.services import jobs as job_service


def conflict_detail(active: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": "A Claude run is already in progress for this bid",
        "activeJob": serialise(active),
    }


def raise_if_pipeline_blocked(active: dict[str, Any] | None, job_type: str) -> None:
    if active and active["type"] != job_type:
        raise HTTPException(409, detail=conflict_detail(active))


async def reserve(project_id: Any, job_type: str) -> dict[str, Any] | None:
    """Decide - and refuse - before the caller writes anything.

    The gate used to run after the PDF had landed, the document row was inserted
    and, for an addendum, a version was snapshotted. A 409 then left all three
    orphaned: a file on disk and a frozen version with no job that would ever
    read them.

    An addendum is the one type that may take the slot rather than be refused.
    It revises a bid that may already be priced, so it has to be recorded
    (Matrix 4.1), and the schema allows one active pipeline job per bid - so
    something gives. A queued run has not started and has read nothing, and the
    addendum changes what it should read, so the addendum supersedes it. A run
    that has already started cannot be interrupted, and that is the one case
    that still returns 409.

    Returns the job it superseded, or None.
    """
    active = await job_service.active_pipeline_job(project_id)
    if active is None or active["type"] == job_type:
        return None

    if job_type != "ingest_addendum" or active["status"] != "queued":
        raise HTTPException(409, detail=conflict_detail(active))

    # Conditional on still being queued: the worker may have claimed it between
    # the read above and this write, and a cancelled-but-running job is exactly
    # the two-writers-one-directory case the exclusivity rule exists to prevent.
    result = await db.jobs.update_one(
        {"_id": active["_id"], "status": "queued"},
        {
            "$set": {
                "status": "cancelled",
                "note": (
                    "superseded by an addendum - re-run once the differences "
                    "have been reviewed"
                ),
                "finishedAt": datetime.now(timezone.utc),
            }
        },
    )
    if not result.matched_count:
        current = await job_service.active_pipeline_job(project_id) or active
        raise HTTPException(409, detail=conflict_detail(current))
    return active


async def enqueue_pipeline(
    job_type: str,
    project_id: Any,
    *,
    payload: dict[str, Any] | None = None,
    actor: str = "estimator",
    delay_seconds: int = 0,
    session=None,
) -> dict[str, Any]:
    """Enqueue when no other pipeline type is active; 409 otherwise."""
    active = await job_service.active_pipeline_job(project_id, session=session)
    raise_if_pipeline_blocked(active, job_type)
    return await job_service.enqueue(
        job_type, project_id, payload, actor, delay_seconds, session=session
    )
