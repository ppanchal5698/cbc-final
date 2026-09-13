"""The extract_bid_set and rerun_extraction jobs: a Claude pass reads the drawings into openings.

Before the pass, extraction.api.passes seeds the sheet map, a door schedule and a
scope floor, and the board follows its progress while it runs. After, what it
wrote is synced into `openings`, the bid's documents move to `read` - or to
`failed` when the job dies - and PDFs that landed mid-pass queue a merge pass
before autopilot moves on.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.extraction.api import documents, openings, passes
from cbc.modules.ops.api import jobs as ops_jobs
from cbc.modules.projects.api import bids, pipeline, saga
from cbc.services import sync  # ponytail: legacy kernel; import_extraction moves here when services/sync_phases is sliced
from cbc.validation.contracts import extraction_review_verdict

JOB_TYPES = ("extract_bid_set", "rerun_extraction")


async def run(job: dict[str, Any]) -> None:
    await pipeline.run_pass(job, sync=sync_results, prepare=passes.prepare, watch=passes.watch_progress)


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    counts = await sync.import_extraction(project, job=job)
    if counts.get("aborted"):
        return "lease stolen; discarded output"
    started = job.get("startedAt") or job.get("createdAt")
    await documents.mark_received(project["_id"], "read", uploaded_by=started)
    if extraction_review_verdict(project["slug"]) == "needs_review":
        await openings.reopen_confirmed(project["_id"])
        await saga.set_state(project["_id"], "extraction_needs_review")
    else:
        await saga.set_state(project["_id"], "extraction_done")
    await bids.set_stage(project["_id"], "extraction", 33)
    return (
        f"{counts['inserted']} new, {counts['updated']} updated, "
        f"{counts['skipped']} left as the estimator set them"
    )


async def after_finish(job: dict[str, Any], status: str, error: str | None, entry: Any) -> None:
    """What follows an extract beyond the queue, before what follows any job.

    A dead pass marks the documents it was reading failed. Either way, PDFs that
    arrived while it ran queue a merge pass - and a done pass then leaves autopilot
    waiting for that merge instead of moving on.
    """
    if status == "dead":
        if job.get("projectId"):
            await documents.mark_received(
                job["projectId"], "failed", uploaded_by=job.get("startedAt") or job.get("createdAt")
            )
            try:
                await _queue_straggler_reextract(job)
            except Exception:
                entry.exception("straggler re-extract after failure failed")
    elif status == "done":
        straggler = None
        try:
            straggler = await _queue_straggler_reextract(job)
        except Exception:
            entry.exception("straggler re-extract enqueue failed after %s", job["type"])
        if straggler:
            entry.info(
                "straggler re-extract queued as %s (autopilot deferred until it finishes)",
                straggler.get("_id"),
            )
            return
    await pipeline.after_pass(job, status, error, entry)


async def _queue_straggler_reextract(job: dict[str, Any]) -> dict[str, Any] | None:
    """If PDFs landed mid-extract, queue a follow-up pass (do not continue autopilot yet)."""
    if job.get("type") not in JOB_TYPES:
        return None
    project_id = job.get("projectId")
    if project_id is None:
        return None

    fresh = await ops_jobs.get(job["_id"]) or job
    started = fresh.get("startedAt") or fresh.get("createdAt")
    stragglers = await documents.count_received_after(project_id, started)
    if not fresh.get("stragglerPending") and not stragglers:
        return None

    payload = dict(fresh.get("payload") or {})
    # Merge-only follow-up: do not rewrite scope_summary / openings from scratch.
    payload["stragglerMerge"] = True
    follow = await ops_jobs.enqueue(
        "extract_bid_set",
        project_id,
        payload=payload,
        actor=fresh.get("createdBy") or "system",
        delay_seconds=ops_jobs.DEFAULT_COALESCE_SECONDS,
    )
    await bids.note_phase(
        project_id,
        "Waiting to merge late uploads",
        "A PDF arrived after extract started; a merge pass will add "
        "only the new file(s) into existing scope and openings before "
        "pricing continues.",
    )
    return follow
