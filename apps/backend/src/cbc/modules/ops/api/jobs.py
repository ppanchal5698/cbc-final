"""Job queue - how the estimator's actions reach Claude Code.

The API enqueues; ops' worker loop claims and runs. Nothing here spawns a
process: extraction on a 30-page CAD set is minutes of work, far longer than a
web request should hold open, and a dropped connection must not lose the job.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection
from cbc.shared.mongo import serialise
from cbc.modules.ops.domain.jobs import EXCLUSIVE_JOB_TYPES
from cbc.modules.ops.api import audit

EXCLUSIVE = set(EXCLUSIVE_JOB_TYPES)



class JobRef(TypedDict, total=False):
    """A stored job, as other modules read it.

    Still the stored document at runtime: a TypedDict converts nothing.
    tests/architecture/test_port_types.py fails when another module reads a field
    not named here.
    """

    _id: ObjectId
    type: str
    projectId: ObjectId | None
    status: str
    payload: dict[str, Any]
    phaseState: dict[str, Any]
    claimGeneration: int
    createdAt: datetime
    createdBy: str
    startedAt: datetime
    stragglerPending: bool
    traceId: str


# Published with job= once a retry has put a dead or failed job back on the queue.
JOB_REQUEUED = "ops.job_requeued"

# Quiet window after each upload so sibling PDFs join the same extract run.
# Default 60s; hard cap (COALESCE_MAX_SECONDS) stops indefinite starvation.
DEFAULT_COALESCE_SECONDS = int(os.environ.get("PIPELINE_DEBOUNCE_SECONDS", "60"))
# Hard cap from the first file in a coalesce window — prevents indefinite starvation
# when uploads keep landing faster than the quiet window. Default 300s (5 min).
COALESCE_MAX_SECONDS = int(os.environ.get("PIPELINE_COALESCE_MAX_SECONDS", "300"))


class PipelineJobActive(Exception):
    """Another pipeline job is already queued or running on this bid."""

    def __init__(self, active: dict[str, Any]) -> None:
        self.active = active
        super().__init__(active.get("type", "pipeline"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _due(delay_seconds: int) -> datetime:
    return _now() + timedelta(seconds=delay_seconds)


def coalesce_ceiling(from_when: datetime | None = None) -> datetime:
    """Latest moment a coalesce window may start the job."""
    return (from_when or _now()) + timedelta(seconds=COALESCE_MAX_SECONDS)


def capped_next_attempt(
    delay_seconds: int,
    coalesce_until: datetime | None,
    *,
    now: datetime | None = None,
) -> datetime:
    """nextAttemptAt = min(now + delay, coalesceUntil). Never past the ceiling."""
    now = now or _now()
    proposed = now + timedelta(seconds=max(delay_seconds, 0))
    if coalesce_until is None:
        return proposed
    return min(proposed, coalesce_until)


def waiting_for_siblings(job: dict[str, Any] | None) -> bool:
    """True when a queued extract is still inside its coalesce quiet window."""
    if not job or job.get("status") != "queued":
        return False
    due = job.get("nextAttemptAt")
    if due is None:
        return False
    if getattr(due, "tzinfo", None) is None:
        due = due.replace(tzinfo=timezone.utc)
    return due > _now()


def coalesce_note(job: dict[str, Any] | None) -> str | None:
    """Human-readable coalesce / straggler status for API + UI."""
    if not job:
        return None
    if job.get("stragglerPending") and job.get("status") == "running":
        return (
            "A later PDF arrived while Claude was already reading. "
            "A merge pass will add only the new file(s) after this pass finishes."
        )
    if waiting_for_siblings(job):
        due = job["nextAttemptAt"]
        if getattr(due, "tzinfo", None) is None:
            due = due.replace(tzinfo=timezone.utc)
        secs = max(0, int((due - _now()).total_seconds()))
        ceiling = job.get("coalesceUntil")
        cap = ""
        if ceiling is not None:
            if getattr(ceiling, "tzinfo", None) is None:
                ceiling = ceiling.replace(tzinfo=timezone.utc)
            cap = f" (hard cap {COALESCE_MAX_SECONDS}s — starts by {ceiling.strftime('%H:%M:%S')} UTC at latest)"
        return (
            f"Waiting ~{secs}s for more files (quiet window {DEFAULT_COALESCE_SECONDS}s)"
            f" before Claude starts reading{cap}."
        )
    return None


# Project-less job types, and the payload field that identifies the same work.
# Indexing is idempotent on the file hash, so a second pass over an unchanged
# sheet is pure waste - and two at once are a write race. Filename is the
# fallback for jobs enqueued before fileSha existed.
COALESCE_BY_PAYLOAD = {
    "index_catalog": "fileSha",
    "parse_catalog": "fileSha",
    "parse_multiplier": "fileSha",
}
COALESCE_FALLBACK = {
    "index_catalog": "filename",
    "parse_catalog": "filename",
    "parse_multiplier": "filename",
}


def _idempotency_key(
    job_type: str, project_id: ObjectId | None, payload: dict[str, Any] | None
) -> str:
    blob = json.dumps(
        {
            "type": job_type,
            "projectId": str(project_id) if project_id else "",
            "payload": payload or {},
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _coalesce_lookup(
    job_type: str, payload: dict[str, Any] | None
) -> tuple[str, Any] | None:
    payload = payload or {}
    primary = COALESCE_BY_PAYLOAD.get(job_type)
    if primary and payload.get(primary):
        return f"payload.{primary}", payload[primary]
    fallback = COALESCE_FALLBACK.get(job_type)
    if fallback and payload.get(fallback):
        return f"payload.{fallback}", payload[fallback]
    return None


async def extend_queued_coalesce(
    job_id: ObjectId, delay_seconds: int, session=None
) -> JobRef | None:
    """Atomically push nextAttemptAt for a still-queued job, capped by coalesceUntil."""
    session_kw = {"session": session} if session is not None else {}
    job = await jobs_collection().find_one({"_id": job_id, "status": "queued"}, **session_kw)
    if not job:
        return None
    ceiling = job.get("coalesceUntil")
    if ceiling is None:
        created = job.get("createdAt") or _now()
        ceiling = coalesce_ceiling(created)
    next_at = capped_next_attempt(delay_seconds, ceiling)
    return await jobs_collection().find_one_and_update(
        {"_id": job_id, "status": "queued"},
        {
            "$set": {
                "nextAttemptAt": next_at,
                "coalesceUntil": ceiling,
            }
        },
        return_document=ReturnDocument.AFTER,
        **session_kw,
    )


async def _mark_straggler(job_id: ObjectId, session=None) -> dict[str, Any] | None:
    """Note that a PDF landed while this extract was already running."""
    session_kw = {"session": session} if session is not None else {}
    return await jobs_collection().find_one_and_update(
        {"_id": job_id, "status": "running"},
        {"$set": {"stragglerPending": True}},
        return_document=ReturnDocument.AFTER,
        **session_kw,
    )


async def enqueue(
    job_type: str,
    project_id: ObjectId | None = None,
    payload: dict[str, Any] | None = None,
    actor: str = "estimator",
    delay_seconds: int = 0,
    session=None,
) -> JobRef:
    """Queue a job. `delay_seconds` holds it back so a burst can coalesce.

    A bid set is often several PDFs, and a run reads the whole of uploads/raw/. A
    pipeline that started on the first file would simply not see the next two, so
    the upload route asks for a short delay and each further upload pushes it out
    — but never past coalesceUntil (PIPELINE_COALESCE_MAX_SECONDS).
    """
    session_kw = {"session": session} if session is not None else {}
    coalesce = _coalesce_lookup(job_type, payload)
    if coalesce and project_id is None:
        field, value = coalesce
        running = await jobs_collection().find_one(
            {
                "type": job_type,
                field: value,
                "status": {"$in": ["queued", "running"]},
            },
            **session_kw,
        )
        if running:
            return running

    if job_type in EXCLUSIVE and project_id is not None:
        running = await active_pipeline_job(project_id, session=session)
        if running:
            # Deliberately permissive: this returns whatever pipeline job is
            # already active, of any type. `enqueue_exclusive` is the strict
            # variant that raises PipelineJobActive instead.
            if running["type"] == job_type and delay_seconds:
                if running["status"] == "queued":
                    extended = await extend_queued_coalesce(
                        running["_id"], delay_seconds, session=session
                    )
                    return extended or running
                if running["status"] == "running":
                    # Late PDF: cannot join this Claude session. Flag a follow-up
                    # extract after the current pass finishes.
                    marked = await _mark_straggler(running["_id"], session=session)
                    return marked or {**running, "stragglerPending": True}
            return running

    now = _now()
    ceiling = coalesce_ceiling(now) if delay_seconds else None
    next_at = capped_next_attempt(delay_seconds, ceiling, now=now) if delay_seconds else None

    job: dict[str, Any] = {
        "type": job_type,
        "projectId": project_id,
        "payload": payload or {},
        "status": "queued",
        "attempts": 0,
        "error": None,
        "log": None,
        "createdBy": actor,
        "createdAt": now,
        "startedAt": None,
        "finishedAt": None,
        "nextAttemptAt": next_at,
        "idempotencyKey": _idempotency_key(job_type, project_id, payload),
    }
    # Top-level only: putting traceId in payload would bust idempotency keys.
    try:
        from cbc.shared import tracing as hop_tracing

        hop = hop_tracing.current_trace_id()
        if hop:
            job["traceId"] = hop
    except Exception:
        pass
    if ceiling is not None:
        job["coalesceUntil"] = ceiling

    try:
        result = await jobs_collection().insert_one(job, **session_kw)
    except DuplicateKeyError:
        if project_id is not None:
            existing = await active_pipeline_job(project_id, session=session)
            if existing:
                if (
                    existing["type"] == job_type
                    and delay_seconds
                    and existing["status"] == "queued"
                ):
                    extended = await extend_queued_coalesce(
                        existing["_id"], delay_seconds, session=session
                    )
                    return extended or existing
                if (
                    existing["type"] == job_type
                    and existing["status"] == "running"
                ):
                    marked = await _mark_straggler(existing["_id"], session=session)
                    return marked or {**existing, "stragglerPending": True}
                return existing
        existing = await jobs_collection().find_one(
            {
                "idempotencyKey": job["idempotencyKey"],
                "status": {"$in": ["queued", "running"]},
            },
            **session_kw,
        )
        if existing:
            return existing
        raise
    job["_id"] = result.inserted_id

    await audit.record(
        action=f"job.enqueue.{job_type}",
        actor=actor,
        target={"projectId": project_id, "jobId": result.inserted_id},
    )
    return job


async def latest_for_project(project_id: ObjectId) -> JobRef | None:
    return await jobs_collection().find_one({"projectId": project_id}, sort=[("createdAt", -1)])


async def active_pipeline_job(
    project_id: ObjectId, session=None
) -> JobRef | None:
    """Newest queued or running pipeline job on this bid (one session per bid)."""
    session_kw = {"session": session} if session is not None else {}
    return await jobs_collection().find_one(
        {
            "projectId": project_id,
            "type": {"$in": list(EXCLUSIVE_JOB_TYPES)},
            "status": {"$in": ["queued", "running"]},
        },
        sort=[("createdAt", -1)],
        **session_kw,
    )


async def enqueue_exclusive(
    job_type: str,
    project_id: ObjectId,
    payload: dict[str, Any] | None = None,
    actor: str = "estimator",
    delay_seconds: int = 0,
) -> JobRef:
    """Queue a pipeline job unless another pipeline type is already active."""
    active = await active_pipeline_job(project_id)
    if active and active["type"] != job_type:
        raise PipelineJobActive(active)
    return await enqueue(job_type, project_id, payload, actor, delay_seconds)


async def active_for_project(project_id: ObjectId) -> JobRef | None:
    """Most recent queued or running job on this bid."""
    return await jobs_collection().find_one(
        {"projectId": project_id, "status": {"$in": ["queued", "running"]}},
        sort=[("createdAt", -1)],
    )


async def holds_lease(job: dict[str, Any]) -> bool:
    """True when this worker's claimGeneration is still the running lease."""
    if job.get("_id") is None:
        return False
    current = await jobs_collection().find_one(
        {
            "_id": job["_id"],
            "workerId": job.get("workerId"),
            "claimGeneration": job.get("claimGeneration"),
            "status": "running",
        },
        {"_id": 1},
    )
    return current is not None


class JobNotRetryable(Exception):
    """Job is not in a state that can be re-queued from the dead-letter queue."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(status)


async def retry(job_id: ObjectId, actor: str = "estimator") -> dict[str, Any]:
    """Re-queue a dead or failed job. Refuses if another pipeline job is active."""
    job = await jobs_collection().find_one({"_id": job_id})
    if job is None:
        raise KeyError(job_id)
    if job.get("status") not in ("dead", "failed"):
        raise JobNotRetryable(str(job.get("status")))
    if job.get("type") in EXCLUSIVE and job.get("projectId") is not None:
        active = await active_pipeline_job(job["projectId"])
        if active is not None and active["_id"] != job["_id"]:
            raise PipelineJobActive(active)
    updated = await jobs_collection().find_one_and_update(
        {"_id": job_id, "status": {"$in": ["dead", "failed"]}},
        {
            "$set": {
                "status": "queued",
                "attempts": 0,
                "error": None,
                "errorCode": None,
                "workerId": None,
                "heartbeatAt": None,
                "finishedAt": None,
                "nextAttemptAt": None,
                "retriedBy": actor,
                "retriedAt": _now(),
                "note": "requeued from dead-letter",
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise JobNotRetryable("gone")
    await audit.record(
        f"job.retry.{updated['type']}",
        actor=actor,
        target={"jobId": job_id, "projectId": updated.get("projectId")},
    )
    return updated


async def active_count(project_id: ObjectId | None = None) -> int:
    query: dict[str, Any] = {"status": {"$in": ["queued", "running"]}}
    if project_id is not None:
        query["projectId"] = project_id
    return await jobs_collection().count_documents(query)


async def metrics(window_hours: int = 24) -> dict[str, Any]:
    """Queue depth, throughput and failure rate, from MongoDB rather than logs.

    The only operational view of the queue was `docker logs`, which cannot answer
    "is it backed up" or "which job type is failing" without someone reading it.
    These are three aggregations over the collection that already holds the
    answer.

    Durations come from startedAt -> finishedAt, so a job still running does not
    drag the average down, and a job that was queued for an hour before a worker
    picked it up does not read as an hour of work.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    depth = {
        row["_id"]: row["count"]
        async for row in jobs_collection().aggregate(
            [
                {"$match": {"status": {"$in": ["queued", "running"]}}},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
        )
    }

    by_type: dict[str, dict[str, Any]] = {}
    async for row in jobs_collection().aggregate(
        [
            {"$match": {"createdAt": {"$gte": since}}},
            {
                "$group": {
                    "_id": {"type": "$type", "status": "$status"},
                    "count": {"$sum": 1},
                    "avgSeconds": {
                        "$avg": {
                            "$cond": [
                                {"$and": ["$startedAt", "$finishedAt"]},
                                {"$divide": [
                                    {"$subtract": ["$finishedAt", "$startedAt"]}, 1000
                                ]},
                                None,
                            ]
                        }
                    },
                }
            },
        ]
    ):
        entry = by_type.setdefault(
            row["_id"]["type"], {"total": 0, "done": 0, "failed": 0, "avgSeconds": None}
        )
        status = row["_id"]["status"]
        entry["total"] += row["count"]
        if status == "done":
            entry["done"] += row["count"]
        elif status in ("failed", "dead"):
            entry["failed"] += row["count"]
        if status == "done" and row.get("avgSeconds") is not None:
            entry["avgSeconds"] = round(row["avgSeconds"], 1)

    finished = sum(e["done"] + e["failed"] for e in by_type.values())
    failed = sum(e["failed"] for e in by_type.values())

    # The oldest thing still waiting is the number that says "backed up", and it
    # is the one a count of queued jobs cannot tell you.
    oldest = await jobs_collection().find_one(
        {"status": "queued"}, {"createdAt": 1}, sort=[("createdAt", 1)]
    )

    return {
        "windowHours": window_hours,
        "queued": depth.get("queued", 0),
        "running": depth.get("running", 0),
        "oldestQueuedAt": oldest.get("createdAt") if oldest else None,
        "finished": finished,
        "failed": failed,
        # None rather than 0 when nothing finished: a 0% failure rate over zero
        # jobs is not good news, it is no news.
        "failureRate": round(failed / finished, 3) if finished else None,
        "byType": by_type,
    }


# ── one Claude session per bid (was http/pipeline_jobs.py) ────────────────────
#
# These used to raise an HTTP 409 from inside queue policy, which tied the
# policy to HTTP and kept anything but a route from reusing it. They raise
# PipelineJobActive now; the composition root maps it to the same 409 and body.


def conflict_detail(active: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": "A Claude run is already in progress for this bid",
        "activeJob": serialise(active),
    }


def raise_if_pipeline_blocked(active: dict[str, Any] | None, job_type: str) -> None:
    if active and active["type"] != job_type:
        raise PipelineJobActive(active)


async def reserve(project_id: Any, job_type: str) -> JobRef | None:
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
    active = await active_pipeline_job(project_id)
    if active is None or active["type"] == job_type:
        return None

    if job_type != "ingest_addendum" or active["status"] != "queued":
        raise PipelineJobActive(active)

    # Conditional on still being queued: the worker may have claimed it between
    # the read above and this write, and a cancelled-but-running job is exactly
    # the two-writers-one-directory case the exclusivity rule exists to prevent.
    result = await jobs_collection().update_one(
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
        current = await active_pipeline_job(project_id) or active
        raise PipelineJobActive(current)
    return active


async def enqueue_pipeline(
    job_type: str,
    project_id: Any,
    *,
    payload: dict[str, Any] | None = None,
    actor: str = "estimator",
    delay_seconds: int = 0,
    session=None,
) -> JobRef:
    """Enqueue when no other pipeline type is active; raise PipelineJobActive otherwise."""
    active = await active_pipeline_job(project_id, session=session)
    raise_if_pipeline_blocked(active, job_type)
    return await enqueue(
        job_type, project_id, payload, actor, delay_seconds, session=session
    )


# ── what other modules ask of the queue about their bids ─────────────────────


async def active_by_project(project_ids) -> dict[Any, JobRef]:
    """The newest queued or running job on each of these bids."""
    # Newest first, so the first one seen per project is the current active job.
    active: dict[Any, dict[str, Any]] = {}
    for job in await jobs_collection().find(
        {"projectId": {"$in": project_ids}, "status": {"$in": ["queued", "running"]}}
    ).sort("createdAt", -1).to_list(length=None):
        active.setdefault(job["projectId"], job)
    return active


async def cancel_active_for_project(project_id: Any, actor: str, *, note: str) -> None:
    """Cancel whatever is queued or running on a bid."""
    await jobs_collection().update_many(
        {"projectId": project_id, "status": {"$in": ["queued", "running"]}},
        {
            "$set": {
                "status": "cancelled",
                "cancelledAt": datetime.now(timezone.utc),
                "cancelledBy": actor,
                "note": note,
            }
        },
    )


async def delete_for_project(project_id: Any) -> None:
    """Remove a bid's job history."""
    await jobs_collection().delete_many({"projectId": project_id})


# ── what a running job reads and records on itself ────────────────────────────


async def get(job_id: Any, projection: dict[str, Any] | None = None) -> JobRef | None:
    return await jobs_collection().find_one({"_id": job_id}, projection)


async def set_fields(job_id: Any, fields: dict[str, Any]) -> None:
    await jobs_collection().update_one({"_id": job_id}, {"$set": fields})


async def unset_fields(job_id: Any, *names: str) -> None:
    await jobs_collection().update_one({"_id": job_id}, {"$unset": {name: "" for name in names}})


async def previous_phase_state(project_id: Any, job_id: Any) -> JobRef | None:
    """The latest other job on this bid that recorded phase progress (B-15)."""
    return await jobs_collection().find_one(
        {
            "projectId": project_id,
            "_id": {"$ne": job_id},
            "phaseState": {"$exists": True, "$ne": {}},
        },
        sort=[("finishedAt", -1), ("createdAt", -1)],
    )
