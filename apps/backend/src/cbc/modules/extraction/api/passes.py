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

from cbc.modules.extraction.api import documents as extraction_documents, openings
from cbc.modules.extraction.infrastructure import geometry
from cbc.modules.ops.api import (
    jobs as ops_jobs,
    runmetrics as ops_runmetrics,
    worker as ops_worker,
)
from cbc.modules.projects.api import bids, lookup, scope_metadata
from cbc.modules.catalog.api import matchcache
from cbc.modules.extraction.infrastructure import pretakeoff, sheetmap, visual_pages
from cbc.shared import manifests, storage
from cbc.shared.pass_files import read_json
from cbc.worker_kit import prompts

# How many pages a single take-off leg is handed. The sheet map ranks them, so
# past this the tail is guesses rather than tagged sheets.
MAX_WAVE_PAGES = 8
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
    ("extracted/line_items.json", "extraction", 40, "Take-off"),
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


async def _parse_signals_by_path(project: dict[str, Any]) -> dict[str, dict[int, dict[str, Any]]]:
    """Parser verified / block counts per raw PDF page, from intake.

    This used to read `intake.infrastructure.collections` directly, past intake's
    api - the layering rule forbids it, and the question is about intake's own
    documents, so intake answers it.
    """
    return await extraction_documents.parse_signals_by_path(
        project.get("_id"), project.get("slug") or ""
    )


async def prepare(job: dict[str, Any], project: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Seed the project tree before a pass reads it: the sheet map, the take-off, the scope floor.

    False when the bid set is over the page cap; the job is finished by then.
    """
    openings_seeded = 0
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
            openings_seeded = int(seeded.get("openings") or 0)
            # The legend that says what each hardware group contains. Without it
            # every group reached pricing as a blank MANUAL line, and the parts
            # that would have used the special-net sheet never left the PDF.
            legend = await asyncio.to_thread(
                pretakeoff.seed_hardware_groups, project["slug"]
            )
            log.info(
                "%s hardware legend: %d set(s), %d item(s) from p%s%s",
                project.get("code", project["slug"]),
                legend["sets"],
                legend["items"],
                legend["pages"] or "-",
                f" - {legend['note']}" if legend["note"] else "",
            )
            log.info(
                "%s pre-take-off: %d openings from p%s (%d estimator rows preserved)%s",
                project.get("code", project["slug"]),
                seeded["openings"],
                seeded["page"],
                seeded["preserved"],
                f" - {seeded['note']}" if seeded["note"] else "",
            )
            signals = await _parse_signals_by_path(project)
            visual = await asyncio.to_thread(
                visual_pages.build_visual_pages,
                project["slug"],
                openings_seeded=openings_seeded,
                signals_by_path=signals or None,
            )
            # Two different numbers, and calling the first one "mandatory" read
            # as though every pre-rendered sheet had to be opened. Most are FRP
            # or finish pages that belong to their own specialist; only the
            # door-schedule subset gates line_items.json.
            rendered = list(visual.get("pages") or [])
            mandatory = [
                page
                for page in rendered
                if isinstance(page, dict)
                and visual_pages.is_door_schedule_visual_page(page)
            ]
            log.info(
                "%s visual pages: %d pre-rendered, %d mandatory for the take-off",
                project.get("code", project["slug"]),
                len(rendered),
                len(mandatory),
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
            if summary.get("div10_in_scope"):
                await asyncio.to_thread(pretakeoff.seed_div10_takeoff, project["slug"])
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

    # The seed is already a real take-off - `seed_door_schedule` writes the rows
    # before the first token is generated, so the model's job is checking them
    # rather than producing them. They were only imported in `sync_results`,
    # which is the job's *completion* hook, so for the whole run the review
    # screen read an empty `openings` collection while telling the estimator
    # "Claude is reading the bid set. Lines appear here as they are found."
    # On a 24-page set that is the parse plus the entire wave - half an hour of
    # a screen that says work is arriving and shows none of it.
    #
    # Importing here puts the seeded rows in front of the estimator while the
    # take-off checks them. The end-of-job import then updates them with its
    # corrections, and a row the estimator confirmed in the meantime is left
    # alone by the same rule that already protects one during a re-run.
    if job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline"):
        from cbc.modules.extraction.api import line_items

        seeded_rows = await line_items.import_extraction(project, job=job)
        if seeded_rows.get("inserted") or seeded_rows.get("updated"):
            log.info(
                "%s seeded openings visible: %d new, %d updated, %d left as the estimator set them",
                project.get("code", project["slug"]),
                seeded_rows.get("inserted", 0),
                seeded_rows.get("updated", 0),
                seeded_rows.get("skipped", 0),
            )
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


async def _apply_match_feedback(job: dict[str, Any]) -> None:
    """Fold the estimator's corrections into what the matcher knows (FR-13).

    Here rather than on a timer because this is the moment it pays: the pass that
    just finished is the one whose output the estimator is about to correct, and
    the next pass should start from those corrections. A learning pass that fails
    must never fail the bid that triggered it.

    Then record what this bid cost in corrections, so the claim that matching is
    improving is a number an operator can read rather than a belief.
    """
    try:
        from cbc.modules.catalog.api.pageindex import reader
        from cbc.modules.extraction.api import feedback
        from cbc.modules.extraction.infrastructure.collections import feedback_events

        await feedback.apply_to_learning()

        project_id = job.get("projectId")
        if not project_id:
            return
        events = feedback_events()
        counts = {
            "total": await events.count_documents({"bidRequestId": project_id}),
            "matchCorrections": await events.count_documents(
                {
                    "bidRequestId": project_id,
                    "eventType": {"$in": sorted(feedback.MATCH_EVENTS)},
                }
            ),
            "pendingLearning": await events.count_documents(
                {"bidRequestId": project_id, "appliedToLearning": False}
            ),
            "learnedSpecifications": await asyncio.to_thread(reader.learned_total),
        }
        await ops_runmetrics.set_estimator_corrections(job, counts)
    except Exception:
        log.exception("match feedback drain failed")

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
    await _apply_match_feedback(job)
    try:
        from cbc.modules.projects.api import pipeline_context

        await asyncio.to_thread(pipeline_context.write_context, slug)
    except Exception:
        log.exception("pipeline_context write failed for %s", slug)

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
    from cbc.modules.ops.api.artifact_gate import ArtifactValidationError

    slug = project["slug"]
    if job["type"] in ("extract_bid_set", "rerun_extraction", "run_full_pipeline"):
        attached, unmatched = geometry.measure_bboxes(project)
        if attached or unmatched:
            log.info(
                "%s bbox: %d measured from the sheet, %d left null and flagged",
                project.get("code", slug), attached, unmatched,
            )
        spec_attached, spec_unmatched = geometry.measure_specialty_bboxes(project)
        if spec_attached or spec_unmatched:
            log.info(
                "%s specialty bbox: %d measured from the sheet, %d left null and flagged",
                project.get("code", slug), spec_attached, spec_unmatched,
            )
        derived, no_depth = geometry.derive_frame_depths(project)
        if derived or no_depth:
            log.info(
                "%s frame depth: %d derived from wall type, %d flagged for review",
                project.get("code", slug), derived, no_depth,
            )

    if job["type"] in ("match_and_price", "run_full_pipeline"):
        from cbc.modules.pricing.api.catalog_baseline_backfill import (
            backfill_priced_lines as catalog_backfill,
        )
        from cbc.modules.pricing.api.list_x_backfill import backfill_priced_lines

        cat_stats = catalog_backfill(slug)
        if cat_stats.get("filled"):
            log.info(
                "%s catalog baseline backfill: %d filled, %d skipped (of %d attempted)",
                project.get("code", slug),
                cat_stats["filled"],
                cat_stats["skipped"],
                cat_stats["attempted"],
            )

        stats = backfill_priced_lines(slug)
        if stats.get("filled"):
            log.info(
                "%s list× backfill: %d filled, %d skipped (of %d attempted)",
                project.get("code", slug),
                stats["filled"],
                stats["skipped"],
                stats["attempted"],
            )

    if job["type"] == "build_proposal":
        _assert_pricing_lines_intact(slug, job)

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


def _assert_pricing_lines_intact(slug: str, job: dict) -> None:
    """Fail proposal sync when live priced lines shrank vs the pricing phase SHA.

    Catches empty-shell overwrites that slipped past promote (e.g. export wipe).
    """
    from cbc.modules.ops.api.artifact_gate import ArtifactValidationError
    from cbc.shared.paths import storage_root
    from cbc.worker_kit.sandbox import _priced_line_count

    live = storage_root() / slug / "priced" / "line_items.json"
    live_n = _priced_line_count(live)
    if live_n is None:
        raise ArtifactValidationError(
            [f"{slug}: priced/line_items.json is invalid JSON"],
            quarantine=[],
            phase_state={},
        )
    phase = (job.get("phaseState") or {}).get("pricing") or {}
    artifacts = phase.get("artifacts") or {}
    expected_sha = artifacts.get("priced/line_items.json")
    if expected_sha and live.is_file():
        import hashlib

        actual = hashlib.sha256(live.read_bytes()).hexdigest()
        if actual != expected_sha and live_n == 0:
            raise ArtifactValidationError(
                [
                    f"{slug}: priced/line_items.json has 0 lines but pricing phase "
                    "recorded a non-empty artifact — refusing proposal sync"
                ],
                quarantine=[],
                phase_state={},
            )
    meta = (job.get("phaseState") or {}).get("pricing") or {}
    recorded_count = meta.get("lineCount")
    if isinstance(recorded_count, int) and recorded_count > 0 and (live_n or 0) < recorded_count:
        raise ArtifactValidationError(
            [
                f"{slug}: priced/line_items.json has {live_n} lines but pricing "
                f"phase recorded {recorded_count} — refusing proposal sync"
            ],
            quarantine=[],
            phase_state={},
        )


async def _persist_phase_state(job: dict, slug: str, phase_state: dict) -> None:
    from cbc.modules.extraction.api.validation.artifacts import PHASE_LABELS

    # Retain earlier validated phases, but never retain a failed current phase
    # or downstream output after its inputs have been regenerated.
    order = ("extraction", "pricing", "proposal")
    current = PHASE_LABELS.get(job["type"], order)[0]
    previous = await asyncio.to_thread(manifests.reusable_phases, slug, job.get("phaseState"))
    phase_state = {
        **{name: entry for name, entry in previous.items() if name in order[:order.index(current)]},
        **phase_state,
    }
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


def extraction_wave(job: dict[str, Any], project: dict[str, Any]) -> list[tuple[str, str]]:
    """The take-offs the worker runs at the same time, as (label, prompt).

    They read different pages and write different files, so nothing in here waits
    on anything else in here. The prompt used to say so and ask the orchestrator
    to launch all three in one message; a measured run launched them in three,
    one after another, and spent 11 of its 17 minutes waiting. An instruction to
    a model is not a mechanism - the worker starts them itself.

    Empty means "run this job as a single pass", which is every other job type
    and any bid whose sheet map named no pages to work from.
    """
    if job["type"] not in ("extract_bid_set", "rerun_extraction"):
        return []
    try:
        sheets = json.loads(sheetmap.sheetmap_path(project["slug"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    def pages_for(*roles: str) -> list[int]:
        seen: list[int] = []
        for hit in sheetmap.pages_for_roles(sheets, *roles):
            try:
                page = int(hit["source_page"])
            except (KeyError, TypeError, ValueError):
                continue
            if page not in seen:
                seen.append(page)
        return seen[:MAX_WAVE_PAGES]

    legs: list[tuple[str, list[int]]] = []
    # Both schedule roles in one ranked pass. The old
    # `pages_for("door_schedule") or pages_for("door_schedule_candidate")` dropped
    # every candidate the moment a single schedule page existed - and the leg was
    # then validated against candidates it was never handed.
    takeoff_pages = pages_for(*visual_pages.DOOR_SCHEDULE_VISUAL_ROLES)
    # The schedule alone cannot answer every field, and the leg used to get
    # nothing else — while the orchestrator path assigns takeoff-engineer
    # door_schedule, door_schedule_candidate, hardware, div08_specs *and*
    # floor_plan, and the 95% ladder in the prompts ends "floor plans (validate /
    # fill gaps)". A real run reported, on every opening in the bid:
    #
    #   "floor-plan swing (sheet A2.0) is outside this session's page scope,
    #    so handing stays flagged rather than filled"
    #
    # Handing is not printed on a door schedule; it is read off the swing. The
    # leg was being asked for a field and denied the sheet that carries it.
    #
    # A small allowance, not the full cap: this bid maps 21 `hardware` pages and
    # 9 `floor_plan`, and opening all of them would cost more than the handful of
    # fields they settle.
    if takeoff_pages:
        # The allowance counts pages the leg does not already have. `pages_for`
        # ranks rather than filters, so the top of every role's list is the same
        # few sheets - taking `[:allowance]` added nothing at all and left the
        # discriminating floor plans, which sit further down, still unseen.
        for role, allowance in (("hardware", 2), ("div08_specs", 2), ("floor_plan", 2)):
            added = 0
            for page in pages_for(role):
                if added >= allowance:
                    break
                if page not in takeoff_pages:
                    takeoff_pages.append(page)
                    added += 1
        # check_extraction requires every schedule/candidate visual page in
        # visual_pages_checked, uncapped. These ride above MAX_WAVE_PAGES - they
        # are not an allowance, the validator holds the leg to every one - so the
        # leg is never validated on a page it was never handed.
        for _path, page in visual_pages.schedule_visual_keys(project["slug"]):
            if page not in takeoff_pages:
                takeoff_pages.append(page)
        legs.append(("takeoff", takeoff_pages))

    # frp/div10 are selected on their sheetmap pages alone. scope_summary only
    # vetoes, and only when a real pass wrote it - the pretakeoff seed's flags
    # just mirror pages_for, so gating on them would be circular, and the scope
    # leg (below) is writing this very file concurrently. So on a first
    # extraction this is behaviour-preserving (seed flag == pages exist), and on
    # rerun_extraction a real pass that set a flag false can veto a stray sheet.
    summary = read_json(storage.project_dir(project["slug"]) / "extracted" / "scope_summary.json")
    summary = summary if isinstance(summary, dict) else {}
    by_real_pass = summary.get("source") not in (None, pretakeoff.SOURCE)

    def _not_vetoed(flag: str) -> bool:
        return not (by_real_pass and summary.get(flag) is False)

    if pages_for("frp") and _not_vetoed("frp_in_scope"):
        legs.append(("frp", pages_for("frp")))
    if pages_for("div10") and _not_vetoed("div10_in_scope"):
        legs.append(("div10", pages_for("div10")))

    # One leg is not a wave. Running it through the fan-out would drop the
    # orchestrator prompt for no benefit - and the orchestrator runs intake and
    # scope itself, so a single-pass extraction still reads the title block/specs.
    if len(legs) < 2:
        return []

    # It IS a wave, so the orchestrator prompt is discarded (claude_pass runs the
    # legs, not the orchestrator). Add the intake and scope legs it would
    # otherwise have run, or scope_metadata.json / scope_summary.json stay at the
    # pretakeoff seed - the title block never read, the specs never read. Their
    # writes are disjoint from every other leg's, so they run beside them.
    # ponytail: a spec-only FRP scope (no tagged sheet) gets no leg on this pass;
    # the scope leg flips the flag and check_extraction warns. If that proves
    # common, make this a two-stage wave (scope first, then specialty selection).
    legs = [
        ("intake", pages_for("title")),
        ("scope", pages_for("div08_specs", "div10")),
    ] + legs

    # Skip legs a previous attempt already promoted, so a retry does not re-buy a
    # ~32k prefix plus turns to re-confirm work already on disk. A leg qualifies
    # only when the last attempt recorded it ok AND its promoted artifact still
    # passes its own contract - res.ok is CLI-level and, on a wave failure, sync
    # never validated it. Three guards the naive version needs:
    #   1. A forced clean run trusts nothing on disk (reintroduces the W3b bug).
    #   2. Validate, don't stat - a promoted-but-unparseable artifact re-runs.
    #   3. If every leg would be skipped, the failure was at promote/sync, not in
    #      a leg, so run the whole wave rather than no-op to success.
    payload = job.get("payload") or {}
    if not payload.get("force"):
        prior_ok = {
            entry.get("label")
            for entry in (job.get("waveLegs") or [])
            if isinstance(entry, dict) and entry.get("ok")
        }
        if prior_ok:
            from cbc.modules.extraction.api.validation import contracts

            remaining: list[tuple[str, list[int]]] = []
            for label, pages in legs:
                artifact = (prompts.WAVE_LEGS.get(label) or {}).get("artifact")
                if label in prior_ok and artifact:
                    kind = Path(artifact).stem
                    problems, _ = contracts.check_contracts(
                        project["slug"], ((artifact, kind),)
                    )
                    if not problems:
                        continue  # done last time and still valid - skip it
                remaining.append((label, pages))
            if remaining:  # empty means re-run everything (failure was promote/sync)
                legs = remaining

    # After skipping, a single remaining leg is still worth a focused re-run
    # rather than dropping back to the whole orchestrator, so build_wave it.
    return prompts.build_wave(job, project, legs)
