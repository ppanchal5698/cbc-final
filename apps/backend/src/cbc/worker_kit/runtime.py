"""The job runner: a claimed job in, what Claude wrote on disk synced out.

ops runs the queue - claiming, leases, reaping, recording how a job ended. This
is what the worker's composition root (cbc/worker/main.py) binds into it: a
headless Claude Code pass or a local handler, then a sync of what Claude wrote
into MongoDB for the UI to serve. It dissolves into the modules that own each
job type as they are built.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Entry point may be run as a file; ensure packages/ is importable before cbc.
def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".mcp.json").exists() or (candidate / "pytest.ini").exists():
            return candidate
    # Container image layout: code under /app with markers at /app.
    fallback = Path("/app")
    if fallback.exists():
        return fallback
    raise RuntimeError(f"cannot locate repository root above {here}")


REPO_ROOT = _repo_root()

from cbc.shared import envfile
from cbc.modules.ops.api import provider

envfile.apply_to_environ(skip=provider.MANAGED)

from cbc.db import db
from cbc.modules.ops.api import jobs as ops_jobs, worker as ops_worker
from cbc.modules.ops.api.worker import finish
from cbc.services import quote as quote_service, render, storage, sync
from cbc.services import manifests, matchcache, pretakeoff, sheetmap
from cbc.modules.ops.api import runmetrics
from cbc.core import claude_cli as runner, streaming
from cbc.shared import logs
from cbc.validation import ArtifactValidationError, validate_job_artifacts
from cbc.validation import review as review_flags
from cbc.worker_kit import prompts
from cbc.modules.catalog.api.jobs import delete_catalog, index_catalog, ingest_pricebook
from cbc.modules.intake.api import documents as intake_documents
from cbc.modules.extraction.api import openings as extraction_openings

log = logs.configure("cbc.worker")

JOB_TIMEOUT = int(os.environ.get("WORKER_JOB_TIMEOUT_SECONDS", "3600"))
# A bound on how far a pass can wander. A run that needs more than this has
# lost the thread, and stopping it is cheaper than letting it finish.
MAX_TURNS = int(os.environ.get("WORKER_MAX_TURNS", "60"))

# A full Phase 0-6 run is nine subagent calls plus the sheet-finding that feeds
# them, on a set that can be 744 pages. Both budgets above are sized for one phase
# and are simply wrong for six.
PIPELINE_TIMEOUT = int(os.environ.get("WORKER_PIPELINE_TIMEOUT_SECONDS", "10800"))
PIPELINE_MAX_TURNS = int(os.environ.get("WORKER_PIPELINE_MAX_TURNS", "200"))
# Per-bid page circuit breaker — refuse Claude before burning tokens on huge sets.
EXTRACT_MAX_PDF_PAGES = int(os.environ.get("EXTRACT_MAX_PDF_PAGES", "400"))


def limits_for(job_type: str) -> tuple[int, int]:
    """(timeout seconds, max turns) for a job type."""
    if job_type == "run_full_pipeline":
        return PIPELINE_TIMEOUT, PIPELINE_MAX_TURNS
    return JOB_TIMEOUT, MAX_TURNS


# Which phase a project has reached, read from what is on disk. An autopilot run is
# one job that can last an hour, and `stage` is only written when a job finishes -
# so without this the board would sit on "intake / 0%" for the whole run.
PIPELINE_PROGRESS = (
    ("review/review_summary.html", "proposal", 95, "Review"),
    ("quotation.html", "proposal", 85, "Quote built"),
    ("priced/line_items.json", "quote", 70, "Pricing"),
    ("extracted/hardware_sets.json", "quote", 55, "Product matching"),
    ("extracted/door_schedule.json", "extraction", 40, "Take-off"),
    ("extracted/scope_summary.json", "extraction", 25, "Spec scoping"),
    ("extracted/scope_metadata.json", "intake", 10, "Intake"),
)


def phase_reached(project_dir: Path) -> tuple[str, int, str] | None:
    """The furthest phase whose output exists, or None if nothing has landed."""
    for relative, stage, progress, label in PIPELINE_PROGRESS:
        if (project_dir / relative).exists():
            return stage, progress, label
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _lease_held(job: dict) -> bool:
    """Running lease still matches this worker's fencing token."""
    from cbc.modules.ops.api.jobs import holds_lease

    return await holds_lease(job)


async def dead_letter(job: dict, detail: str) -> None:
    """Mark the bid's saga as blocked and ping operators."""
    from cbc.modules.ops.api import alerts
    from cbc.modules.projects.api import saga as chain

    job_type = job.get("type") or ""
    state = chain.FAIL_STATE.get(job_type, "awaiting_manual_retry")
    await chain.set_state(job.get("projectId"), state, detail=detail)
    code = ""
    if job.get("projectId") is not None:
        project = await db.projects.find_one({"_id": job["projectId"]}, {"code": 1})
        code = (project or {}).get("code") or ""
    alerts.notify(
        f"Dead-letter: {job_type} on {code or 'unknown bid'} — {detail}",
        extra={
            "jobId": str(job.get("_id")),
            "jobType": job_type,
            "projectCode": code,
        },
    )


async def _quarantine(job: dict, project: dict | None, rows: list[dict]) -> None:
    if not rows:
        return
    docs = []
    for row in rows:
        docs.append(
            {
                "projectId": (project or {}).get("_id") or job.get("projectId"),
                "jobId": job.get("_id"),
                "claimGeneration": job.get("claimGeneration"),
                "relPath": row.get("relPath"),
                "raw": row.get("raw"),
                "errors": row.get("errors") or [],
                "createdAt": _now(),
            }
        )
    if docs:
        await extraction_openings.record_failed(docs)


async def after_finish(job: dict, status: str, error: str | None, entry) -> None:
    """What follows a finished job beyond the queue.

    ops' finish() records how the job ended, then calls this with the outcome:
    the bid's documents and late uploads after an extract, the dead letter, and
    autopilot's next step. A retry is not an ending and never reaches here. The
    worker's composition root binds it.
    """
    if status == "dead":
        if job["type"] in ("extract_bid_set", "rerun_extraction") and job.get("projectId"):
            await _mark_docs_for_pass(
                job["projectId"],
                job.get("startedAt") or job.get("createdAt"),
                state="failed",
            )
            try:
                await _queue_straggler_reextract(job)
            except Exception:
                entry.exception("straggler re-extract after failure failed")
        await dead_letter(job, error or "job failed")
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
        else:
            try:
                from cbc.modules.projects.api import autopilot as orchestrator

                nxt = await orchestrator.maybe_continue_chain(job)
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
                    from cbc.modules.projects.api import autopilot as orch

                    nxt_type = orch.next_in_chain(job["type"])
                except Exception:
                    pass
                await _note_autopilot_break(
                    job, next_type=nxt_type, detail=str(exc) or "continuation error"
                )


def _derive_review_flags(job_type: str, slug: str) -> None:
    """Write the mechanical review findings before the summary is rendered.

    Reported rather than raised, like the renders: a project whose artifacts are
    too broken to derive flags from is a project whose flags the estimator most
    needs, and losing the job would take the rest of the pass with it.
    """
    try:
        count = review_flags.write_flags(slug)
        log.info("%s: %d review flag(s) derived", job_type, count)
    except Exception:
        log.exception("%s: could not derive review flags for %s", job_type, slug)


async def _mark_docs_for_pass(
    project_id: Any, started_at: datetime | None, *, state: str
) -> int:
    """Flip documents that belonged to this pass; leave later uploads alone."""
    return await intake_documents.mark_received(project_id, state, uploaded_by=started_at)


async def _queue_straggler_reextract(job: dict[str, Any]) -> dict[str, Any] | None:
    """If PDFs landed mid-extract, queue a follow-up pass (do not continue autopilot yet)."""
    if job.get("type") not in ("extract_bid_set", "rerun_extraction"):
        return None
    project_id = job.get("projectId")
    if project_id is None:
        return None

    fresh = await ops_jobs.get(job["_id"]) or job
    started = fresh.get("startedAt") or fresh.get("createdAt")
    stragglers = await intake_documents.count_received_after(project_id, started)
    if not fresh.get("stragglerPending") and not stragglers:
        return None

    from cbc.modules.ops.api import jobs as job_service

    payload = dict(fresh.get("payload") or {})
    # Merge-only follow-up: do not rewrite scope_summary / openings from scratch.
    payload["stragglerMerge"] = True
    follow = await job_service.enqueue(
        "extract_bid_set",
        project_id,
        payload=payload,
        actor=fresh.get("createdBy") or "system",
        delay_seconds=job_service.DEFAULT_COALESCE_SECONDS,
    )
    await db.projects.update_one(
        {"_id": project_id},
        {
            "$set": {
                "phase": "Waiting to merge late uploads",
                "pipelineNote": (
                    "A PDF arrived after extract started; a merge pass will add "
                    "only the new file(s) into existing scope and openings before "
                    "pricing continues."
                ),
                "updatedAt": _now(),
            }
        },
    )
    return follow


async def _note_autopilot_break(
    job: dict[str, Any], *, next_type: str | None, detail: str
) -> None:
    project_id = job.get("projectId")
    if project_id is None:
        return
    await db.projects.update_one(
        {"_id": project_id},
        {
            "$set": {
                "phase": f"Autopilot stopped after {job.get('type')}",
                "pipelineNote": (
                    f"Could not continue to {next_type or 'next stage'}: {detail}. "
                    "Stage stays where the last successful pass left it — review and re-run."
                ),
                "updatedAt": _now(),
            }
        },
    )


def _sync_blocking_pre(job: dict, project: dict) -> dict:
    """BBox measurement, frame depths, and artifact validation — all sync I/O."""
    slug = project["slug"]
    if job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline"):
        attached, unmatched = sync.measure_bboxes(project)
        if attached or unmatched:
            log.info(
                "%s bbox: %d measured from the sheet, %d left null and flagged",
                project.get("code", slug), attached, unmatched,
            )
        derived, no_depth = sync.derive_frame_depths(project)
        if derived or no_depth:
            log.info(
                "%s frame depth: %d derived from wall type, %d flagged for review",
                project.get("code", slug), derived, no_depth,
            )

    if job["type"] in (
        "extract_bid_set",
        "rerun_extraction",
        "match_and_price",
        "build_proposal",
        "run_full_pipeline",
    ):
        from cbc.validation.contracts import raise_if_invalid

        raise_if_invalid(job["type"], slug)
        return validate_job_artifacts(job["type"], slug) or {}
    return {}


def _sync_blocking_render(job_type: str, slug: str) -> list[str]:
    """Derive review flags and render proposal artifacts. Returns failure details."""
    _derive_review_flags(job_type, slug)
    failed: list[str] = []
    for result in (render.render_quotation(slug), render.render_review_summary(slug)):
        if not result.ok:
            log.warning("%s: %s", job_type, result.detail)
            failed.append(result.detail)
    return failed


async def _persist_phase_state(job: dict, slug: str, phase_state: dict) -> None:
    if not phase_state:
        return
    await asyncio.to_thread(manifests.stamp_phase, slug, phase_state)
    await ops_jobs.set_fields(job["_id"], {"phaseState": phase_state})
    job["phaseState"] = phase_state


async def _inherit_phase_state(job: dict, project: dict) -> dict:
    """Copy still-valid phases from the previous job on this bid (B-15)."""
    prev = await ops_jobs.previous_phase_state(project["_id"], job["_id"])
    if not prev:
        return {}
    kept = manifests.reusable_phases(project["slug"], prev.get("phaseState") or {})
    if kept:
        await ops_jobs.set_fields(job["_id"], {"phaseState": kept})
    return kept


async def sync_results(job: dict, project: dict | None) -> str:
    """Move what Claude wrote on disk into Mongo.

    Aborts without writing when this worker no longer holds the claimGeneration
    lease — a reaped worker must discard its output rather than race the new owner.
    """
    if project is None:
        return ""

    if not await _lease_held(job):
        if await ops_worker.job_cancelled(job["_id"]):
            raise RuntimeError("cancelled by estimator")
        log.warning(
            "job %s sync skipped - claim was reaped or taken by another worker",
            job.get("type"),
        )
        return "lease stolen; discarded output"

    slug = project["slug"]
    try:
        phase_state = await asyncio.to_thread(_sync_blocking_pre, job, project)
    except ArtifactValidationError as exc:
        await _quarantine(job, project, getattr(exc, "quarantine", []) or [])
        await _persist_phase_state(job, slug, exc.phase_state or {})
        if job["type"] in matchcache.JOB_TYPES:
            await asyncio.to_thread(matchcache.ingest, slug)
        raise
    await _persist_phase_state(job, slug, phase_state or {})
    if job["type"] in matchcache.JOB_TYPES:
        await asyncio.to_thread(matchcache.ingest, slug)

    if not await _lease_held(job):
        if await ops_worker.job_cancelled(job["_id"]):
            raise RuntimeError("cancelled by estimator")
        log.warning(
            "job %s sync skipped after validation - lease stolen",
            job.get("type"),
        )
        return "lease stolen; discarded output"

    from cbc.modules.projects.api import saga as chain
    from cbc.validation.contracts import extraction_review_verdict

    if job["type"] in ("extract_bid_set", "rerun_extraction"):
        counts = await sync.import_extraction(project, job=job)
        if counts.get("aborted"):
            return "lease stolen; discarded output"
        started = job.get("startedAt") or job.get("createdAt")
        await intake_documents.mark_received(project["_id"], "read", uploaded_by=started)
        verdict = extraction_review_verdict(slug)
        if verdict == "needs_review":
            await extraction_openings.reopen_confirmed(project["_id"])
            await chain.set_state(
                project["_id"],
                "extraction_needs_review",
            )
            await db.projects.update_one(
                {"_id": project["_id"]},
                {"$set": {"stage": "extraction", "progress": 33, "updatedAt": _now()}},
            )
        else:
            await chain.set_state(project["_id"], "extraction_done")
            await db.projects.update_one(
                {"_id": project["_id"]},
                {
                    "$set": {
                        "stage": "extraction",
                        "progress": 33,
                        "updatedAt": _now(),
                    },
                },
            )
        return (
            f"{counts['inserted']} new, {counts['updated']} updated, "
            f"{counts['skipped']} left as the estimator set them"
        )

    if job["type"] == "match_and_price":
        counts = await sync.import_quote_lines(project, job=job)
        if counts.get("aborted"):
            return "lease stolen; discarded output"
        await quote_service.persist(project)
        from cbc.services import matching_gate

        await matching_gate.apply_to_project(project)
        await db.projects.update_one(
            {"_id": project["_id"]},
            {"$set": {"stage": "quote", "progress": 67, "updatedAt": _now()}},
        )
        return f"{counts['inserted']} priced, {counts['updated']} updated, {counts['skipped']} kept"

    if job["type"] == "run_full_pipeline":
        openings = await sync.import_extraction(project, job=job)
        if openings.get("aborted"):
            return "lease stolen; discarded output"
        await intake_documents.mark_all_read(project["_id"])
        if not await _lease_held(job):
            return "lease stolen; discarded output"
        priced = await sync.import_quote_lines(project, job=job)
        if priced.get("aborted"):
            return "lease stolen; discarded output"
        await quote_service.persist(project)
        failed = await asyncio.to_thread(_sync_blocking_render, job["type"], slug)
        artifacts = await sync.import_proposal_artifacts(project)
        await chain.set_state(project["_id"], "complete")
        await db.projects.update_one(
            {"_id": project["_id"]},
            {"$set": {"stage": "proposal", "progress": 100, "updatedAt": _now()}},
        )
        written = sum(1 for present in artifacts.values() if present)
        note = (
            f"{openings['inserted'] + openings['updated']} opening(s), "
            f"{priced['inserted'] + priced['updated']} priced line(s), "
            f"{written} proposal artifact(s) - draft ready for estimator review"
        )
        return f"{note} ({'; '.join(failed)})" if failed else note

    if job["type"] == "build_proposal":
        if not await _lease_held(job):
            return "lease stolen; discarded output"
        failed = await asyncio.to_thread(_sync_blocking_render, job["type"], slug)
        artifacts = await sync.import_proposal_artifacts(project)
        await chain.set_state(project["_id"], "complete")
        await db.projects.update_one(
            {"_id": project["_id"]},
            {"$set": {"stage": "proposal", "progress": 100, "updatedAt": _now()}},
        )
        written = sum(1 for present in artifacts.values() if present)
        note = f"{written} proposal artifact(s) synced from disk"
        return f"{note} ({'; '.join(failed)})" if failed else note

    if job["type"] == "ingest_addendum":
        counts = await sync.import_addendum(project, job)
        return (
            f"{counts['added']} added, {counts['removed']} removed, "
            f"{counts['changed']} changed in addendum diff"
        )

    return ""


# Jobs the worker performs itself. Indexing a price book is deterministic
# extraction into SQLite - there is no reasoning in it, so spending a Claude pass
# (and its minutes, and its tokens) on it would be waste.
LOCAL_HANDLERS = {
    "index_catalog": index_catalog,
    "delete_catalog": delete_catalog,
}


async def _record_runmetrics(
    job: dict,
    recording: Path,
    prompt: str,
    project: dict | None,
    described: dict | None,
    error_code: str | None = None,
) -> None:
    """Parse the Claude recording after every post-CLI finish(). Never raises."""
    try:
        current = await ops_jobs.get(
            job["_id"],
            {"status": 1, "errorCode": 1, "startedAt": 1, "finishedAt": 1, "provider": 1},
        )
        merged = {**job, **(current or {})}
        await runmetrics.record(
            merged,
            recording,
            prompt=prompt,
            project=project,
            provider=described or merged.get("provider"),
            outcome_status=merged.get("status"),
            error_code=error_code or merged.get("errorCode"),
        )
    except Exception:
        log.exception("runmetrics failed for job %s", job.get("_id"))


async def process_locally(job: dict) -> None:
    """Run a job in this process rather than through a Claude Code pass."""
    handler = LOCAL_HANDLERS[job["type"]]
    heartbeat = asyncio.create_task(ops_worker.beat(job["_id"], job.get("workerId", ops_worker.WORKER_ID), job.get("claimGeneration", 0)))
    try:
        note = await handler(job)
    except Exception as exc:
        log.exception("%s failed", job["type"])
        # A bad payload, a missing file, or a layout the extractor cannot read all
        # read exactly the same way on the third attempt. Retrying them spends the
        # attempt budget to reach the same conclusion more slowly.
        from cbc.modules.catalog.api.jobs import IndexingError

        permanent = isinstance(exc, (ValueError, FileNotFoundError, IndexingError))
        await finish(job, False, str(exc), "", permanent=permanent)
        return
    finally:
        heartbeat.cancel()
    await finish(job, True, None, "", note)


async def process(job: dict) -> None:
    """Run one claimed job; optional OTLP span when OTEL endpoint is set."""
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
        await _process_body(job)


async def _process_body(job: dict) -> None:
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
    if job["type"] in LOCAL_HANDLERS:
        await process_locally(job)
        return

    project = None
    if job.get("projectId"):
        project = await db.projects.find_one({"_id": job["projectId"]})
        if project is None:
            await finish(job, False, "project no longer exists", "")
            return
        storage.scaffold(project["slug"])
        from cbc.modules.projects.api import saga as chain_service

        start = chain_service.START_STATE.get(job["type"])
        if start:
            await chain_service.set_state(project["_id"], start)

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

    payload = job.setdefault("payload", {})
    if job["type"] == "ingest_pricebook":
        # Assigned, never defaulted. `POST /api/jobs` takes a free-form payload, and
        # a `setdefault` here let the caller choose a path that the ingest handler
        # then read and unlinked - arbitrary file deletion through the jobs API.
        payload["outputPath"] = f".cache/pricebook-{job['_id']}.json"

    # Catalog `force` reindexes a sheet; pipeline `force` means rebuild phases.
    # Do not mix the two.
    if (
        project is not None
        and job["type"] in sheetmap.SHEETMAP_JOB_TYPES | {"match_and_price", "build_proposal"}
        and payload.get("force")
    ):
        await ops_jobs.unset_fields(job["_id"], "phaseState")
        job.pop("phaseState", None)

    if (
        project is not None
        and job["type"] == "run_full_pipeline"
        and not payload.get("force")
    ):
        inherited = await _inherit_phase_state(job, project)
        if inherited:
            job["phaseState"] = inherited

    if project is not None and job["type"] in sheetmap.SHEETMAP_JOB_TYPES:
        await asyncio.to_thread(
            sheetmap.build_sheetmap,
            project["slug"],
            force=bool(payload.get("force")),
        )
        # And then do the take-off itself, in code. The prompt used to ask the
        # model to run parse_schedule.py; a model that ignores the instruction
        # left the job with no schedule at all. Seeding it here means the phase
        # has an artifact before the first token is generated, and the model's
        # job becomes checking rows rather than producing them.
        if job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline"):
            seeded = await asyncio.to_thread(pretakeoff.seed_door_schedule, project["slug"])
            log.info(
                "%s pre-take-off: %d openings from p%s (%d estimator rows preserved)%s",
                project.get("code", project["slug"]),
                seeded["openings"],
                seeded["page"],
                seeded["preserved"],
                f" - {seeded['note']}" if seeded["note"] else "",
            )
        # The scope files are required for the run to validate at all. Seed a
        # truthful floor - known values in, everything else null and flagged -
        # only where the file does not exist yet, so a real pass always wins.
        if job["type"] in ("extract_bid_set", "run_full_pipeline"):
            summary = await asyncio.to_thread(pretakeoff.seed_scope_summary, project["slug"])
            metadata = await asyncio.to_thread(
                pretakeoff.seed_scope_metadata, project["slug"], project
            )
            if summary.get("frp_in_scope"):
                await asyncio.to_thread(pretakeoff.seed_frp_takeoff, project["slug"])
            log.info(
                "%s scope floor: summary %s, metadata %s",
                project.get("code", project["slug"]),
                "seeded" if summary.get("written") else summary.get("note"),
                "seeded" if metadata.get("written") else metadata.get("note"),
            )

    # Cumulative over all uploads/raw — re-checked on every extract_bid_set,
    # including stragglerMerge follow-ups (late PDFs can push the set over the cap).
    if (
        project is not None
        and job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline")
        and EXTRACT_MAX_PDF_PAGES > 0
    ):
        over, pages = await asyncio.to_thread(
            sheetmap.exceeds_page_cap, project["slug"], EXTRACT_MAX_PDF_PAGES
        )
        if over:
            merge = " (straggler merge; set still subject to page cap)" if payload.get(
                "stragglerMerge"
            ) else ""
            detail = (
                f"Bid set has {pages} pages (cap EXTRACT_MAX_PDF_PAGES="
                f"{EXTRACT_MAX_PDF_PAGES}){merge}. Split the set or raise the cap."
            )
            await db.projects.update_one(
                {"_id": project["_id"]},
                {
                    "$set": {
                        "phase": "Extract blocked — set too large",
                        "pipelineNote": detail,
                        "updatedAt": _now(),
                    }
                },
            )
            await finish(
                job,
                False,
                detail,
                "",
                permanent=True,
                error_code="extract_too_large",
            )
            return

    # Read the provider on every job, so changing it on the settings screen takes
    # effect on the next job rather than on the next worker restart.
    config = await ops_worker.claude_config()
    env, _ = provider.build_env(config)
    described = provider.describe(config)

    log.info(
        "running %s%s via %s (%s)",
        job["type"],
        f" for {project['code']}" if project else "",
        described["mode"],
        described["model"],
    )
    # A provider that cannot call the Agent tool is told to do the phases itself.
    # Handing it the delegating prompt is what produced a run that made seven tool
    # calls in twelve minutes and wrote nothing.
    delegates = provider.supports_subagents(config)
    if not delegates:
        log.info("provider cannot delegate; using the solo prompt for %s", job["type"])
    prompt = prompts.build(job, project, delegates=delegates)

    from cbc.db import readonly_uri

    if job["type"] in ("match_and_price", "ingest_pricebook") and not readonly_uri():
        await finish(
            job,
            False,
            "catalog unavailable: set MONGODB_READONLY_URI before pricing jobs",
            "",
            error_code="catalog_unavailable",
        )
        return

    # Where the estimator watches this happen. Recorded per job under the project
    # so the session can be replayed after the fact, not only while it runs.
    attempt = max(int(job.get("attempts") or 1), 1)
    recording = streaming.recording_path(
        project["slug"] if project else None,
        str(job["_id"]),
        REPO_ROOT,
        attempt=attempt,
    )
    if attempt > 1:
        await asyncio.to_thread(streaming.write_retry_banner, recording, attempt)
    await ops_jobs.set_fields(
        job["_id"], {"recording": str(recording.relative_to(REPO_ROOT)).replace("\\", "/")}
    )

    timeout, max_turns = limits_for(job["type"])
    cancel_event = threading.Event()

    async def watch_cancel() -> None:
        while not cancel_event.is_set():
            # A shutdown stops the subprocess the same way a cancel does. Without
            # this the container's grace period expires mid-run and the job is
            # SIGKILLed into a permanent `running`.
            if ops_worker.stopping():
                cancel_event.set()
                return
            if await ops_worker.job_cancelled(job["_id"]):
                cancel_event.set()
                return
            await asyncio.sleep(1)

    from cbc.worker_kit import sandbox as sandbox_mod

    sandbox_ws: Path | None = None
    if project is not None:
        try:
            sandbox_ws = await asyncio.to_thread(
                sandbox_mod.prepare, str(job["_id"]), project["slug"]
            )
            env = sandbox_mod.env_for(sandbox_ws, env)
        except Exception:
            log.exception("sandbox prepare failed; running against the live project tree")
            sandbox_ws = None

    if sandbox_ws is not None and project is not None:
        progress_dir = sandbox_ws / "projects" / project["slug"]
    elif project is not None:
        progress_dir = Path(storage.project_dir(project["slug"]))
    else:
        progress_dir = None

    # Rebind the directory the progress watcher polls.
    if progress_dir is not None:
        watch_progress_dir = progress_dir
    else:
        watch_progress_dir = None

    async def watch_progress_bound() -> None:
        if project is None or watch_progress_dir is None:
            return
        if job["type"] not in (
            "run_full_pipeline",
            "extract_bid_set",
            "rerun_extraction",
        ):
            return
        directory = watch_progress_dir
        last: tuple[str, int, str] | None = None
        metadata_synced = False
        while True:
            meta_path = directory / "extracted" / "scope_metadata.json"
            if not metadata_synced and meta_path.exists():
                try:
                    raw_text = meta_path.read_text(encoding="utf-8")
                    parsed = json.loads(raw_text)
                    if not isinstance(parsed, dict):
                        raise json.JSONDecodeError("not an object", raw_text, 0)
                except (OSError, json.JSONDecodeError, UnicodeError):
                    await asyncio.sleep(2)
                    continue
                fresh = await db.projects.find_one({"_id": project["_id"]}) or project
                try:
                    filled = await sync.import_scope_metadata(fresh)
                except Exception:
                    log.exception(
                        "%s mid-run scope metadata sync failed", project.get("code")
                    )
                    filled = False
                metadata_synced = True
                if filled:
                    await db.projects.update_one(
                        {"_id": project["_id"]},
                        {
                            "$set": {
                                "phase": "Job record filled from drawings",
                                "pipelineNote": (
                                    "Empty create-form fields were filled from the "
                                    "bid PDF with page citations. Take-off continues."
                                ),
                                "updatedAt": _now(),
                            }
                        },
                    )
            reached = phase_reached(directory)
            if reached and reached != last:
                stage, progress, label = reached
                await db.projects.update_one(
                    {"_id": project["_id"]},
                    {"$set": {"stage": stage, "progress": progress,
                              "phase": label, "updatedAt": _now()}},
                )
                log.info("%s reached %s (%s%%)", project["code"], label, progress)
                last = reached
            await asyncio.sleep(10)

    loop = asyncio.get_running_loop()
    worker_id = job.get("workerId", ops_worker.WORKER_ID)
    claim_gen = job.get("claimGeneration", 0)

    def ping() -> None:
        async def _write() -> None:
            try:
                await ops_worker.heartbeat_once(job["_id"], worker_id, claim_gen)
            except Exception as exc:  # noqa: BLE001
                log.warning("wrapper heartbeat for job %s failed: %s", job["_id"], exc)

        try:
            asyncio.run_coroutine_threadsafe(_write(), loop).result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("wrapper heartbeat for job %s failed: %s", job["_id"], exc)

    def run_cli():
        kwargs = dict(
            prompt=prompt,
            timeout=timeout,
            env=env,
            redact_values=provider.secret_values(config),
            recording=recording,
            job_type=job["type"],
            max_turns=max_turns,
            cancel_check=cancel_event.is_set,
            settings=provider.claude_settings_overlay(config),
            on_heartbeat=ping,
            heartbeat_seconds=ops_worker.HEARTBEAT_SECONDS,
            cwd=sandbox_ws,
        )
        if sandbox_mod.mode() == "docker":
            return sandbox_mod.run_claude_docker(**kwargs)
        return runner.run_claude(**kwargs)

    watcher = asyncio.create_task(watch_cancel())
    heartbeat = asyncio.create_task(
        ops_worker.beat(job["_id"], worker_id, claim_gen)
    )
    progress_watcher = asyncio.create_task(watch_progress_bound())
    result = None
    try:
        result = await asyncio.to_thread(run_cli)
    finally:
        cancel_event.set()
        watcher.cancel()
        heartbeat.cancel()
        progress_watcher.cancel()
        if sandbox_ws is not None and project is not None and result is not None and result.ok:
            try:
                await asyncio.to_thread(sandbox_mod.promote, str(job["_id"]), project["slug"])
            except Exception:
                log.exception("sandbox promote failed for job %s", job["_id"])
        if sandbox_ws is not None:
            try:
                await asyncio.to_thread(sandbox_mod.cleanup, str(job["_id"]))
            except Exception:
                log.exception("sandbox cleanup failed for job %s", job["_id"])

    # Stopped because the worker is going down, not because anyone asked. Put it
    # back on the queue rather than recording a failure nobody caused.
    if result is None:
        raise RuntimeError("Claude wrapper returned no result")

    if ops_worker.stopping() and not result.ok:
        # Two guards finish() has always had and this did not.
        #
        # Ownership: an unfiltered write here requeued a job this worker no
        # longer held - reaped, re-claimed and already running elsewhere - so a
        # third worker picked it up and two Claude passes wrote
        # projects/{slug}/priced/line_items.json at once.
        #
        # And `result.ok`: a SIGTERM arriving after a successful run but before
        # finish() threw the completed pass away and decremented attempts, so a
        # three-hour extraction ran again from the start on restart.
        if await ops_worker.requeue_for_shutdown(job):
            log.info("job %s requeued for shutdown", job["type"])
            return

    # Recorded so "which provider produced this line?" is answerable months later,
    # the same question NFR-3 asks of every price.
    await ops_jobs.set_fields(job["_id"], {"provider": described})

    # And carried onto the bid itself when the provider is one Claude Code warns
    # about. A draft that looks finished but was produced on a model that could
    # not delegate is silently wrong at the level of the whole document - the
    # estimator has to be able to see that without reading the job log.
    if project is not None:
        degraded = bool(described.get("warnings"))
        await db.projects.update_one(
            {"_id": project["_id"]},
            {"$set": {
                "producedBy": {**described, "degraded": degraded},
                "degraded": degraded,
            }},
        )

    recording_note = ""
    if recording.exists():
        try:
            raw = await asyncio.to_thread(
                recording.read_text, encoding="utf-8", errors="replace"
            )
            rec_warnings = streaming.recording_warnings(raw)
            if rec_warnings:
                recording_note = "; ".join(rec_warnings)
        except OSError:
            pass
    if described.get("warnings"):
        provider_note = "; ".join(described["warnings"])
        recording_note = f"{recording_note}; {provider_note}" if recording_note else provider_note

    if not result.ok:
        await finish(
            job,
            False,
            result.error,
            result.output,
            permanent=result.permanent,
            error_code=result.error_code,
        )
        await _record_runmetrics(
            job, recording, prompt, project, described, result.error_code
        )
        return

    try:
        note = (
            await ingest_pricebook(job)
            if job["type"] == "ingest_pricebook"
            else await sync_results(job, project)
        )
    except ArtifactValidationError as exc:
        await finish(
            job,
            False,
            str(exc),
            result.output,
            permanent=True,
            error_code="artifact_validation",
        )
        await _record_runmetrics(
            job, recording, prompt, project, described, "artifact_validation"
        )
        return
    except Exception as exc:  # a sync failure is a real failure - do not mask it
        if str(exc) == "cancelled by estimator":
            await finish(job, False, "cancelled by estimator", result.output)
            await _record_runmetrics(job, recording, prompt, project, described)
            return
        await finish(job, False, f"result sync failed: {exc}", result.output, error_code="sync_failed")
        await _record_runmetrics(
            job, recording, prompt, project, described, "sync_failed"
        )
        return

    combined = note
    if recording_note:
        combined = f"{note}; {recording_note}" if note else recording_note
    await finish(job, True, None, result.output, combined or None)
    await _record_runmetrics(job, recording, prompt, project, described)


