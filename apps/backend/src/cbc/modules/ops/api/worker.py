"""What a job's handler needs from the queue while it holds a claimed job.

ops' worker loop claims a job and hands it to the handler registered here for its
type: a job slice in the module that owns the work, registered from that module's
`register_jobs` by the worker's composition root, cbc/worker/main.py. The handler
calls back into these to keep its lease alive, to notice a cancel or a shutdown,
and to record how the job ended.

claimGeneration is the fencing token throughout: nothing here writes to a job
this worker no longer holds.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from cbc.modules.ops.api import audit, provider
from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection, settings_collection
from cbc.modules.ops.domain.jobs import EXCLUSIVE_JOB_TYPES
from cbc.shared import logs

log = logging.getLogger("cbc.worker")  # handlers are configured by the worker process


MAX_ATTEMPTS = int(os.environ.get("WORKER_MAX_ATTEMPTS", "3"))


# A running job says so every HEARTBEAT_SECONDS. Nothing else distinguishes "this
# is a 40-minute extraction" from "the worker that claimed this was killed an hour
# ago", and without that distinction a dead job holds the exclusive-job index
# against its project forever.
#
# claimGeneration is the fencing token (lease) for a claim. finish() and a
# pass's output check only commit when workerId + claimGeneration still match.
HEARTBEAT_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_SECONDS", "30"))


# Retry delay: RETRY_BASE * 2**attempts. Without it a job that fails in two
# seconds burns its whole attempt budget in six.
RETRY_BASE_SECONDS = int(os.environ.get("WORKER_RETRY_BASE_SECONDS", "30"))


# Identifies this process when claiming jobs. A stale reaper can hand the same
# job to another worker; finish() only writes when workerId and claimGeneration
# still match, so a slow worker cannot overwrite a faster one's terminal state.
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


# Set by the worker's signal handlers. A Claude pass checks it, so a shutdown
# stops it the same way a cancel does.
_stop = asyncio.Event()


def stopping() -> bool:
    return _stop.is_set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


Handler = Callable[[dict[str, Any]], Awaitable[None]]
AfterFinish = Callable[[dict[str, Any], str, str | None, Any], Awaitable[None]]
OnDead = Callable[[dict[str, Any], str], Awaitable[None]]

_handlers: dict[str, Handler] = {}
_after: dict[str, AfterFinish] = {}
_after_finish: AfterFinish | None = None
_on_dead: OnDead | None = None


def register(job_type: str, handler: Handler, *, after_finish: AfterFinish | None = None) -> None:
    """Plug in what runs a claimed job of this type - and, when the job has more to
    do when it ends than the default, what follows.

    ops cannot import the code that runs a job: it belongs to the modules that
    own each job type, and they depend on ops. Each module registers its job
    slices from `register_jobs`, which the worker's composition root calls.
    """
    _handlers[job_type] = handler
    if after_finish is not None:
        _after[job_type] = after_finish


def bind(*, after_finish: AfterFinish, on_dead: OnDead) -> None:
    """What follows any job's end unless its type registered its own, and whom a
    dead job tells - the bid's saga, the operators. The worker's root binds both."""
    global _after_finish, _on_dead
    _after_finish, _on_dead = after_finish, on_dead


def bound() -> bool:
    return bool(_handlers)


async def run(job: dict[str, Any]) -> None:
    """Run one claimed job with its type's handler; an OTLP span when OTEL is on."""
    from cbc.shared import otel

    payload = job.get("payload") or {}
    trace_id = job.get("traceId") or payload.get("traceId")
    with otel.span(
        f"job.{job.get('type', 'unknown')}",
        attributes={
            "job.id": str(job.get("_id")),
            "job.type": job.get("type"),
            "cbc.trace_id": trace_id,
        },
    ):
        handler = _handlers.get(job.get("type"))
        if handler is None:
            raise RuntimeError(
                f"no handler registered for job type {job.get('type')!r}; "
                "the worker's composition root registers them"
            )
        await handler(job)


async def run_locally(
    job: dict[str, Any],
    *,
    work: Callable[[dict[str, Any]], Awaitable[str]],
    permanent: tuple[type[BaseException], ...],
) -> None:
    """Run a job in this process rather than through a Claude pass: beat while
    `work` runs, then finish with its note. An exception in `permanent` fails the
    job without spending the rest of its attempts."""
    heartbeat = asyncio.create_task(
        beat(job["_id"], job.get("workerId", WORKER_ID), job.get("claimGeneration", 0))
    )
    try:
        note = await work(job)
    except Exception as exc:
        log.exception("%s failed", job["type"])
        await finish(job, False, str(exc), "", permanent=isinstance(exc, permanent))
        return
    finally:
        heartbeat.cancel()
    await finish(job, True, None, "", note)


async def dead_letter(job: dict[str, Any], detail: str) -> None:
    """A job is dead: tell whoever owns what it was doing - the bid's saga, the operators."""
    if _on_dead is not None:
        await _on_dead(job, detail)


async def claude_config() -> dict[str, Any]:
    """The provider configuration, read per job so a change on the settings screen
    takes effect on the next job rather than on the next worker restart."""
    return await settings_collection().find_one({"_id": "claude"}) or provider.default_config()


async def heartbeat_once(job_id: Any, worker_id: str, claim_gen: int) -> None:
    """Stamp the heartbeat - only while this worker still holds the claim."""
    await jobs_collection().update_one(
        {"_id": job_id, "workerId": worker_id, "claimGeneration": claim_gen},
        {"$set": {"heartbeatAt": _now()}},
    )


async def beat(job_id, worker_id: str, claim_gen: int) -> None:
    """Say the job is still alive until this task is cancelled.

    One unhandled exception here killed the task for the rest of the run, with
    the exception never retrieved. Ninety seconds later reap_abandoned saw a
    stale heartbeat and requeued a job that was still running, and another
    worker claimed it - two Claude passes over the same project directory,
    because of one transient Mongo blip during a forty-minute pipeline.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            await heartbeat_once(job_id, worker_id, claim_gen)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a missed beat is not fatal
            log.warning("heartbeat for job %s failed, will retry: %s", job_id, exc)


def owns_job(job: dict, current: dict | None) -> bool:
    """True when this worker's claim is still the active one."""
    if not current:
        return False
    return (
        current.get("workerId") == job.get("workerId")
        and current.get("claimGeneration") == job.get("claimGeneration")
    )


async def job_cancelled(job_id) -> bool:
    doc = await jobs_collection().find_one({"_id": job_id}, {"status": 1})
    return bool(doc and doc.get("status") == "cancelled")


async def finish(
    job: dict,
    ok: bool,
    error: str | None,
    output: str,
    note: str = "",
    permanent: bool = False,
    error_code: str | None = None,
) -> None:
    current = await jobs_collection().find_one(
        {"_id": job["_id"]},
        {"status": 1, "workerId": 1, "claimGeneration": 1},
    )
    if current and current.get("status") == "cancelled":
        await jobs_collection().update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "log": (output or "")[-8000:],
                    "note": note or error or "cancelled by estimator",
                    "finishedAt": _now(),
                }
            },
        )
        await audit.record(
            f"job.cancelled.{job['type']}",
            actor="claude",
            target={"jobId": job["_id"], "projectId": job.get("projectId")},
            note=error or note,
        )
        log.info("job %s cancelled - left as cancelled", job["type"])
        return

    if error == "cancelled by estimator":
        await jobs_collection().update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": "cancelled",
                    "error": error,
                    "log": (output or "")[-8000:],
                    "note": note or None,
                    "finishedAt": _now(),
                }
            },
        )
        await audit.record(
            f"job.cancelled.{job['type']}",
            actor="claude",
            target={"jobId": job["_id"], "projectId": job.get("projectId")},
        )
        log.info("job %s cancelled during run", job["type"])
        return

    if not owns_job(job, current):
        log.warning(
            "job %s completion ignored - claim was reaped or taken by another worker",
            job["type"],
        )
        return

    attempts = job.get("attempts", 1)
    retryable = not ok and not permanent and attempts < MAX_ATTEMPTS
    if ok:
        status = "done"
    elif retryable:
        status = "queued"
    else:
        status = "dead"

    await jobs_collection().update_one(
        {
            "_id": job["_id"],
            "workerId": job.get("workerId"),
            "claimGeneration": job.get("claimGeneration"),
        },
        {
                "$set": {
                    "status": status,
                    "error": error,
                    "errorCode": error_code,
                    "log": (output or "")[-8000:],
                "note": note or None,
                "heartbeatAt": None,
                "nextAttemptAt": (
                    _now() + timedelta(seconds=RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0))
                    if retryable
                    else None
                ),
                "finishedAt": None if retryable else _now(),
            }
        },
    )
    await audit.record(
        f"job.{status}.{job['type']}",
        actor="claude",
        target={"jobId": job["_id"], "projectId": job.get("projectId")},
        note=error or note or None,
    )

    # Bound rather than formatted in: under LOG_FORMAT=json these are their own
    # keys, so "every failure of this job type on this project" is a query rather
    # than a regex over sentences.
    entry = logs.bind(
        log,
        job_id=str(job["_id"]),
        job_type=job["type"],
        project_id=str(job["projectId"]) if job.get("projectId") else None,
        attempt=attempts,
        trace_id=job.get("traceId") or (job.get("payload") or {}).get("traceId"),
    )
    if retryable:
        entry.warning(
            "job %s failed, retrying in %ss (attempt %s): %s",
            job["type"],
            RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0),
            attempts,
            error,
        )
    elif not ok:
        entry.error("job %s FAILED%s: %s", job["type"], " permanently" if permanent else "", error)
    else:
        entry.info("job %s done - %s", job["type"], note or "no changes reported")

    # What follows beyond the queue - the bid's documents and late uploads, the
    # dead letter, autopilot's next step - belongs to whoever ran the job. A retry
    # is not an ending: the old finish() did nothing past its log line for one.
    hook = _after.get(job["type"], _after_finish)
    if hook is not None and not retryable:
        await hook(job, status, error, entry)


async def requeue_for_shutdown(job: dict[str, Any]) -> bool:
    """Put a job this worker was stopped in the middle of back on the queue.

    Only while this worker still holds the claim, and never over a cancel. False
    when it did nothing, so the caller records the run as it ended.
    """
    current = await jobs_collection().find_one(
        {"_id": job["_id"]}, {"status": 1, "workerId": 1, "claimGeneration": 1}
    )
    if not (owns_job(job, current) and current.get("status") != "cancelled"):
        return False
    await jobs_collection().update_one(
        {
            "_id": job["_id"],
            "workerId": job.get("workerId"),
            "claimGeneration": job.get("claimGeneration"),
        },
        {
            "$set": {
                "status": "queued",
                "startedAt": None,
                "heartbeatAt": None,
                "nextAttemptAt": None,
                "workerId": None,
                "note": "worker shut down mid-run; requeued",
            },
            "$inc": {"attempts": -1},
        },
    )
    return True


async def defer_if_bid_busy(job: dict[str, Any]) -> dict[str, Any] | None:
    """One Claude session per bid, held when a job runs as well as when it is queued.

    When another pipeline job is already running on this job's bid - a reap or a
    claim race that enqueue could not see - put this one back on the queue for a
    short wait and return the job it is waiting for. None when it may run.
    """
    if (
        job.get("projectId") is None
        or job["type"] not in EXCLUSIVE_JOB_TYPES
        or job.get("status") != "running"
    ):
        return None
    other = await jobs_collection().find_one(
        {
            "projectId": job["projectId"],
            "type": {"$in": list(EXCLUSIVE_JOB_TYPES)},
            "status": "running",
            "_id": {"$ne": job["_id"]},
        }
    )
    if not other:
        return None
    await jobs_collection().update_one(
        {
            "_id": job["_id"],
            "status": "running",
            "workerId": job.get("workerId"),
            "claimGeneration": job.get("claimGeneration"),
        },
        {
            "$set": {
                "status": "queued",
                "startedAt": None,
                "heartbeatAt": None,
                "workerId": None,
                "nextAttemptAt": _now() + timedelta(seconds=15),
                "note": (
                    f"waiting for {other['type']} job {other['_id']} "
                    "to finish (one session per bid)"
                ),
            },
            "$inc": {"attempts": -1},
        },
    )
    return other
