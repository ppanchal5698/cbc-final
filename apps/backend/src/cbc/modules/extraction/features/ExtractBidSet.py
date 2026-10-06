"""The extract_bid_set and rerun_extraction jobs: the drawings read into openings.

Two engines, chosen in Settings > Pipeline:

- **v2** reads the bid set in code. extraction.api.passes seeds it before the
  job's work - the sheet map, the door schedule over every schedule sheet, the
  hardware legend, the scope, the Division 10 and FRP take-offs - and the work
  measures what has no highlight yet and lands the rows. What a drawing did not
  say is a flag on its row for the estimator, never a failed job.
- **legacy** is the Claude pass: seeded the same way, then checked by the agents
  and validated before it lands.

After either, the rows are in `openings`, the bid's documents move to `read` - or
to `failed` when the job dies - and PDFs that landed mid-pass queue a merge pass
before autopilot moves on.
"""
from __future__ import annotations

import asyncio
from typing import Any

from cbc.modules.extraction.api import documents, line_items, openings, passes
from cbc.modules.extraction.features import ReadByModel
from cbc.modules.extraction.infrastructure import pretakeoff
from cbc.modules.ops.api import jobs as ops_jobs, pipeline as ops_pipeline
from cbc.modules.projects.api import bids, lookup, pipeline, saga
from cbc.modules.extraction.api.validation.contracts import extraction_review_verdict

JOB_TYPES = ("extract_bid_set", "rerun_extraction")


async def run(job: dict[str, Any]) -> None:
    if await ops_pipeline.extraction_engine() == "v2":
        await pipeline.run_pass(job, sync=sync_results, prepare=passes.prepare, work=extract_in_code)
        return
    await pipeline.run_pass(
        job,
        sync=sync_results,
        prepare=passes.prepare,
        watch=passes.watch_progress,
        # The three take-offs start together. Nothing in wave 2 reads another's
        # output, and asking the orchestrator to launch them in one message did
        # not make it happen.
        wave_for=passes.extraction_wave,
    )


async def extract_in_code(job: dict[str, Any], project: dict[str, Any]) -> str:
    """The v2 pass, after `prepare` has read the bid set: measure, then land it."""
    project = await lookup.get(project["_id"]) or project
    slug = project["slug"]
    if job["type"] == "rerun_extraction":
        # Nothing but the seeds writes the specialty take-offs in code, so a re-run
        # reads them again too; their importer keeps what the estimator decided.
        scope = await asyncio.to_thread(pretakeoff.seed_scope_summary, slug)
        if scope.get("frp_in_scope"):
            await asyncio.to_thread(pretakeoff.seed_frp_takeoff, slug)
        if scope.get("div10_in_scope"):
            await asyncio.to_thread(pretakeoff.seed_div10_takeoff, slug)
    # What the parsers cannot read, asked of the model - each answer only where the
    # take-off has nothing, and flagged for the estimator to confirm.
    tables = await ReadByModel.schedules(slug)
    titled = await ReadByModel.title_block(slug)
    handed = await ReadByModel.handing(slug)
    if not await ops_jobs.holds_lease(job):
        return "lease stolen; discarded output"
    # Every box came off the text layer already; only what has none is measured.
    await asyncio.to_thread(passes.measure, project, overwrite=False)
    note = await _land(job, project)
    asked = [f"{tables.get('doors', 0)} door(s) and {tables.get('sets', 0)} hardware set(s) off pictures "
             "of the sheets" if any(tables.values()) else "",
             f"{titled} project field(s) off the title block" if titled else "",
             f"handing off the plan for {handed}" if handed else ""]
    return "; ".join([note, *filter(None, asked)])


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    # The bid as it is now: an estimator may have filled a field or deleted a row
    # while the pass ran, and the import must not undo either.
    return await _land(job, await lookup.get(project["_id"]) or project)


async def _land(job: dict[str, Any], project: dict[str, Any]) -> str:
    """The take-off into `openings`, the documents read, the review verdict."""
    counts = await line_items.import_extraction(project, job=job)
    if counts.get("aborted"):
        return "lease stolen; discarded output"
    from cbc.modules.extraction.api import specialty_takeoffs

    specialties = await specialty_takeoffs.import_specialty_takeoffs(project, job=job)
    if specialties.get("aborted"):
        return "lease stolen; discarded specialty takeoffs"
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
        f"{counts['skipped']} left as the estimator set them; "
        f"specialties frp={specialties.get('frp', 0)} div10={specialties.get('div10', 0)}"
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
