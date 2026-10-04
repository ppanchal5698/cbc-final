"""The bid's side of every pipeline job: the bid a pass runs over, and what follows when a job ends.

The job slices in extraction, quoting and intake say what their pass means. This
loads the bid, starts its saga, holds one Claude session per bid and hands the
pass to ops. `after_pass` and `dead_letter` are what follows any job's end unless
its type registered its own; the worker's composition root binds them into ops.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from cbc.modules.ops.api import alerts, claude_pass, jobs as ops_jobs, worker as ops_worker
from cbc.modules.projects.api import autopilot, bids, lookup, saga
from cbc.modules.projects.infrastructure.collections import bid_requests
from cbc.shared import manifests, storage
from cbc.shared import logs

log = logging.getLogger("cbc.worker")  # handlers are configured by the worker process

# Seeds the project tree before the pass reads it; False when it has already finished the job.
Prepare = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], Awaitable[bool]]


WaveFor = Callable[[dict[str, Any], dict[str, Any]], list[tuple[str, str]]]


async def run_pass(
    job: dict[str, Any],
    *,
    sync: claude_pass.Sync,
    prepare: Prepare | None = None,
    watch: claude_pass.Watch | None = None,
    needs_catalog: bool = False,
    wave_for: WaveFor | None = None,
) -> None:
    """Run a Claude pass over the job's bid: `prepare(job, project, payload)`, then claude_pass.run."""
    # Prefer top-level job.traceId (set at enqueue); payload is a fallback only.
    payload = job.get("payload") or {}
    trace_id = job.get("traceId") or payload.get("traceId")
    job_log = logs.bind(
        log,
        job_id=str(job["_id"]),
        job_type=job["type"],
        project_id=str(job["projectId"]) if job.get("projectId") else None,
        trace_id=trace_id,
    )

    project = None
    if job.get("projectId"):
        project = await lookup.get(job["projectId"])
        if project is None:
            await ops_worker.finish(job, False, "project no longer exists", "")
            return
        storage.scaffold(project["slug"])
        start = saga.START_STATE.get(job["type"])
        if start:
            await saga.set_state(project["_id"], start)

    # One Claude session per bid: if another pipeline job is still running on this
    # project, defer until it finishes (handles reaper/claim races).
    if project is not None:
        other = await ops_worker.defer_if_bid_busy(job)
        if other:
            job_log.info(
                "job %s (%s) blocked by concurrent pipeline job %s (%s)",
                job["_id"],
                job["type"],
                other["_id"],
                other["type"],
            )
            return
        # When PARSER_URL is set, Claude must not start (and prepare must not
        # seed from the PDF) until the parser has finished or failed every in-flight
        # parse on this bid. When PARSER_URL is empty, this is a no-op and Claude
        # extracts with pdf-tools as before.
        waiting = await ops_worker.defer_if_parsing(job)
        if waiting:
            job_log.info(
                "job %s (%s) waiting for parse job %s",
                job["_id"],
                job["type"],
                waiting["_id"],
            )
            return

    payload = job.setdefault("payload", {})
    # Catalog `force` reindexes a sheet; pipeline `force` means rebuild phases.
    # Do not mix the two.
    if project is not None and payload.get("force"):
        await ops_jobs.unset_fields(job["_id"], "phaseState")
        job.pop("phaseState", None)

    if project is not None and prepare is not None and not await prepare(job, project, payload):
        return

    if project is not None and job["type"] in (
        "extract_bid_set", "rerun_extraction", "match_and_price", "build_proposal", "run_full_pipeline"
    ) and not payload.get("force"):
        await _inherit_phase_state(job, project)

    # Built here rather than at enqueue: it reads the sheet map that `prepare`
    # has only just written.
    wave = None
    if wave_for is not None and project is not None:
        legs = wave_for(job, project)
        if legs:
            wave = [claude_pass.WavePass(label=label, prompt=text) for label, text in legs]

    await claude_pass.run(
        job,
        project,
        sync=sync,
        watch=watch,
        on_provider=_record_provider,
        needs_catalog=needs_catalog,
        wave=wave,
    )


async def _inherit_phase_state(job: dict, project: dict) -> None:
    """Carry validated artifacts between the current split-phase jobs too."""
    previous = await ops_jobs.previous_phase_state(project["_id"], job["_id"])
    state = {**((previous or {}).get("phaseState") or {}), **(job.get("phaseState") or {})}
    kept = await asyncio.to_thread(manifests.reusable_phases, project["slug"], state)
    await ops_jobs.set_fields(job["_id"], {"phaseState": kept})
    job["phaseState"] = kept


async def _record_provider(project: dict[str, Any], described: dict[str, Any]) -> None:
    """Which provider produced the pass, carried onto the bid itself.

    When the provider is one Claude Code warns about, a draft that looks finished
    but was produced on a model that could not delegate is silently wrong at the
    level of the whole document - the estimator has to be able to see that
    without reading the job log.
    """
    degraded = bool(described.get("warnings"))
    await bid_requests().update_one(
        {"_id": project["_id"]},
        {"$set": {
            "producedBy": {**described, "degraded": degraded},
            "degraded": degraded,
        }},
    )


async def dead_letter(job: dict[str, Any], detail: str) -> None:
    """Mark the bid's saga as blocked and ping operators."""
    job_type = job.get("type") or ""
    state = saga.FAIL_STATE.get(job_type, "awaiting_manual_retry")
    await saga.set_state(job.get("projectId"), state, detail=detail)
    code = ""
    if job.get("projectId") is not None:
        project = await bid_requests().find_one({"_id": job["projectId"]}, {"code": 1})
        code = (project or {}).get("code") or ""
    alerts.notify(
        f"Dead-letter: {job_type} on {code or 'unknown bid'} — {detail}",
        extra={
            "jobId": str(job.get("_id")),
            "jobType": job_type,
            "projectCode": code,
        },
    )


async def after_pass(job: dict[str, Any], status: str, error: str | None, entry: Any) -> None:
    """What follows a finished job beyond the queue: the dead letter, or autopilot's next step.

    ops' finish() calls it with the outcome; a retry is not an ending and never
    reaches here. A job type with more to do when it ends - an extract's documents
    and late uploads - registers its own hook, which calls this after.
    """
    if status == "dead":
        await dead_letter(job, error or "job failed")
    elif status == "done":
        try:
            nxt = await autopilot.maybe_continue_chain(job)
            if nxt:
                entry.info(
                    "orchestrate: queued %s as %s",
                    nxt["type"],
                    nxt["_id"],
                )
        except Exception as exc:
            entry.exception("orchestrate continuation failed after %s", job["type"])
            nxt_type = None
            try:
                nxt_type = autopilot.next_in_chain(job["type"])
            except Exception:
                pass
            await _note_autopilot_break(
                job, next_type=nxt_type, detail=str(exc) or "continuation error"
            )


async def _note_autopilot_break(
    job: dict[str, Any], *, next_type: str | None, detail: str
) -> None:
    project_id = job.get("projectId")
    if project_id is None:
        return
    await bids.note_phase(
        project_id,
        f"Autopilot stopped after {job.get('type')}",
        f"Could not continue to {next_type or 'next stage'}: {detail}. "
        "Stage stays where the last successful pass left it — review and re-run.",
    )
