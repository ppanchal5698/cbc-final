"""What every pass over a bid does on disk around its Claude run: seed the tree before, check it after.

Shared by the pass slices - extraction's ExtractBidSet, quoting's MatchAndPrice and
BuildProposal, intake's IngestAddendum and RunFullPipeline. Output that fails its
schema is quarantined into `failedExtractions`, which extraction owns, so this
sits in the lowest module every one of them may import.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.modules.extraction.api import openings
from cbc.modules.extraction.infrastructure import geometry
from cbc.modules.ops.api import jobs as ops_jobs, worker as ops_worker
from cbc.modules.projects.api import bids, lookup, scope_metadata
from cbc.modules.catalog.api import matchcache
from cbc.modules.extraction.infrastructure import pretakeoff, sheetmap
from cbc.shared import manifests
from cbc.modules.extraction.api.validation import ArtifactValidationError, validate_job_artifacts
from cbc.modules.extraction.api.validation.contracts import raise_if_invalid

log = logging.getLogger("cbc.worker")  # handlers are configured by the worker process

# Per-bid page circuit breaker — refuse Claude before burning tokens on huge sets.
EXTRACT_MAX_PDF_PAGES = int(os.environ.get("EXTRACT_MAX_PDF_PAGES", "400"))

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


async def prepare(job: dict[str, Any], project: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Seed the project tree before a pass reads it: the sheet map, the take-off, the scope floor.

    False when the bid set is over the page cap; the job is finished by then.
    """
    if job["type"] in sheetmap.SHEETMAP_JOB_TYPES:
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
        job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline")
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
            await bids.note_phase(project["_id"], "Extract blocked — set too large", detail)
            await ops_worker.finish(
                job,
                False,
                detail,
                "",
                permanent=True,
                error_code="extract_too_large",
            )
            return False
    return True


async def watch_progress(project: dict[str, Any], directory: Path) -> None:
    """Move the board along while a long pass runs, from what has landed in `directory`.

    The bid's empty create-form fields are filled from scope_metadata.json as soon
    as the pass writes it, with page citations. Runs until the pass cancels it.
    """
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
            fresh = await lookup.get(project["_id"]) or project
            try:
                filled = await scope_metadata.import_scope_metadata(fresh)
            except Exception:
                log.exception(
                    "%s mid-run scope metadata sync failed", project.get("code")
                )
                filled = False
            metadata_synced = True
            if filled:
                await bids.note_phase(
                    project["_id"],
                    "Job record filled from drawings",
                    "Empty create-form fields were filled from the "
                    "bid PDF with page citations. Take-off continues.",
                )
        reached = phase_reached(directory)
        if reached and reached != last:
            stage, progress, label = reached
            await bids.set_stage(project["_id"], stage, progress, phase=label)
            log.info("%s reached %s (%s%%)", project["code"], label, progress)
            last = reached
        await asyncio.sleep(10)


async def check_output(job: dict[str, Any], project: dict[str, Any] | None) -> str | None:
    """Whether a pass's output may be synced - every pass slice asks before it writes.

    None when it may. A note to finish the job with when the output must be
    discarded: this worker no longer holds the claimGeneration lease, and a reaped
    worker must not race the new owner. Raises ArtifactValidationError, once the
    rows that failed are quarantined, when the output does not validate.
    """
    if project is None:
        return ""

    if not await ops_jobs.holds_lease(job):
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

    if not await ops_jobs.holds_lease(job):
        if await ops_worker.job_cancelled(job["_id"]):
            raise RuntimeError("cancelled by estimator")
        log.warning(
            "job %s sync skipped after validation - lease stolen",
            job.get("type"),
        )
        return "lease stolen; discarded output"
    return None


def _sync_blocking_pre(job: dict, project: dict) -> dict:
    """BBox measurement, frame depths, and artifact validation — all sync I/O."""
    slug = project["slug"]
    if job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline"):
        attached, unmatched = geometry.measure_bboxes(project)
        if attached or unmatched:
            log.info(
                "%s bbox: %d measured from the sheet, %d left null and flagged",
                project.get("code", slug), attached, unmatched,
            )
        derived, no_depth = geometry.derive_frame_depths(project)
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
        raise_if_invalid(job["type"], slug)
        return validate_job_artifacts(job["type"], slug) or {}
    return {}


async def _persist_phase_state(job: dict, slug: str, phase_state: dict) -> None:
    if not phase_state:
        return
    await asyncio.to_thread(manifests.stamp_phase, slug, phase_state)
    await ops_jobs.set_fields(job["_id"], {"phaseState": phase_state})
    job["phaseState"] = phase_state


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
        await openings.record_failed(docs)
