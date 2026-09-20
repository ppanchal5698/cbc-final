"""A headless Claude Code pass over a claimed job: prompt, run, record, finish.

The job slices that own each pass decide what it means - what to seed before it
and how to read back what it wrote. This is what every pass shares: the provider,
the recording the estimator watches, the sandbox, cancel and shutdown, the
heartbeat, and how the job ends. A pass over a bid comes here through
cbc.modules.projects.api.pipeline, which loads the bid first; the price-book
ingest, which has no bid, calls it directly.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, NamedTuple

from cbc.modules.ops.api import claude_cli as runner
from cbc.modules.ops.infrastructure import streaming
from cbc.modules.ops.api import jobs as ops_jobs, provider, runmetrics, worker as ops_worker
from cbc.modules.ops.api.worker import finish
from cbc.shared import storage
from cbc.shared.paths import repo_root
from cbc.modules.ops.api.artifact_gate import ArtifactValidationError
from cbc.worker_kit import prompts

log = logging.getLogger("cbc.worker")  # handlers are configured by the worker process

REPO_ROOT = repo_root()

JOB_TIMEOUT = int(os.environ.get("WORKER_JOB_TIMEOUT_SECONDS", "3600"))
# A bound on how far a pass can wander. A run that needs more than this has
# lost the thread, and stopping it is cheaper than letting it finish.
MAX_TURNS = int(os.environ.get("WORKER_MAX_TURNS", "60"))

# A full Phase 0-6 run is nine subagent calls plus the sheet-finding that feeds
# them, on a set that can be 744 pages. Both budgets above are sized for one phase
# and are simply wrong for six.
PIPELINE_TIMEOUT = int(os.environ.get("WORKER_PIPELINE_TIMEOUT_SECONDS", "10800"))
PIPELINE_MAX_TURNS = int(os.environ.get("WORKER_PIPELINE_MAX_TURNS", "200"))

# What a job slice hands the pass: how to sync its output (returning the job's
# note), what to watch while it runs, and who records the provider on the bid.
Sync = Callable[[dict[str, Any], dict[str, Any] | None], Awaitable[str]]
Watch = Callable[[dict[str, Any], Path], Awaitable[None]]
OnProvider = Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]


class WavePass(NamedTuple):
    """One Claude pass in a wave that the worker runs itself.

    Wave 2 of an extraction is three take-offs that read different pages and
    write different files. Nothing in it reads another's output, so nothing in it
    has to wait - and yet a measured run spent 11 of its 17 minutes doing exactly
    that, because the orchestrator emitted its three `Agent` calls in three
    separate messages instead of one.

    Asking a model to parallelise is not a mechanism. The worker starts these
    together, in one shared sandbox: disjoint writes, so a single promote at the
    end needs no merge.
    """

    label: str
    prompt: str


def _combine(legs: list[WavePass], results: list[runner.RunResult]) -> runner.RunResult:
    """One result for a wave. Every failure is named, not just the first.

    A wave is not all-or-nothing on the artifacts - each leg has already written
    what it finished - but the job is only a success when every leg was.
    """
    failed = [(leg, res) for leg, res in zip(legs, results) if not res.ok]
    output = "\n".join(
        f"--- {leg.label} ---\n{res.output or ''}" for leg, res in zip(legs, results)
    )
    if not failed:
        return runner.RunResult(ok=True, output=output, error=None, returncode=0)
    return runner.RunResult(
        ok=False,
        output=output,
        error="; ".join(f"{leg.label}: {res.error}" for leg, res in failed),
        returncode=next(res.returncode for _leg, res in failed),
        permanent=all(res.permanent for _leg, res in failed),
        error_code=next((res.error_code for _leg, res in failed if res.error_code), None),
    )


def limits_for(job_type: str) -> tuple[int, int]:
    """(timeout seconds, max turns) for a job type."""
    if job_type == "run_full_pipeline":
        return PIPELINE_TIMEOUT, PIPELINE_MAX_TURNS
    return JOB_TIMEOUT, MAX_TURNS


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


async def run(
    job: dict[str, Any],
    project: dict[str, Any] | None,
    *,
    sync: Sync,
    watch: Watch | None = None,
    on_provider: OnProvider | None = None,
    needs_catalog: bool = False,
    wave: list[WavePass] | None = None,
) -> None:
    """Run one Claude pass for a claimed job, sync what it wrote, and finish the job.

    `project` is the bid the pass works on, or None. `needs_catalog` refuses the
    pass when the catalog server would have no read-only credential.
    """
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

    from cbc.shared.mongo import readonly_uri

    if needs_catalog and not readonly_uri():
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
    legs = list(wave) if wave else [WavePass(label="", prompt=prompt)]
    recordings = [
        streaming.recording_path(
            project["slug"] if project else None,
            str(job["_id"]),
            REPO_ROOT,
            attempt=attempt,
            label=leg.label or None,
        )
        for leg in legs
    ]
    # The first is the job's recording, so a single-pass job is unchanged and a
    # wave still has one log the run page opens by default.
    recording = recordings[0]
    if attempt > 1:
        for path in recordings:
            await asyncio.to_thread(streaming.write_retry_banner, path, attempt)

    def _rel(path: Path) -> str:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")

    fields: dict[str, Any] = {"recording": _rel(recording)}
    if len(legs) > 1:
        fields["recordings"] = [
            {"label": leg.label, "path": _rel(path)} for leg, path in zip(legs, recordings)
        ]
    await ops_jobs.set_fields(job["_id"], fields)

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

    async def watch_progress_bound() -> None:
        if watch is None or project is None or progress_dir is None:
            return
        await watch(project, progress_dir)

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

    def run_leg(leg: WavePass, leg_recording: Path):
        kwargs = dict(
            prompt=leg.prompt,
            timeout=timeout,
            env=env,
            redact_values=provider.secret_values(config),
            recording=leg_recording,
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
        if len(legs) == 1:
            result = await asyncio.to_thread(run_leg, legs[0], recordings[0])
        else:
            # Started in one gather, so they overlap rather than queue. They share
            # one sandbox and write different files; the single promote below
            # copies all of it back with nothing to reconcile.
            log.info(
                "%s wave: starting %s concurrently",
                job["type"],
                ", ".join(leg.label for leg in legs),
            )
            result = _combine(
                legs,
                list(
                    await asyncio.gather(
                        *(
                            asyncio.to_thread(run_leg, leg, path)
                            for leg, path in zip(legs, recordings)
                        )
                    )
                ),
            )
    finally:
        cancel_event.set()
        watcher.cancel()
        heartbeat.cancel()
        progress_watcher.cancel()
        promote_ok = True
        if sandbox_ws is not None and project is not None and result is not None and result.ok:
            try:
                await asyncio.to_thread(sandbox_mod.promote, str(job["_id"]), project["slug"])
            except Exception as exc:
                promote_ok = False
                log.exception("sandbox promote failed for job %s", job["_id"])
                from cbc.worker_kit.sandbox import EmptyPricingPromoteError

                error_code = (
                    EmptyPricingPromoteError.error_code
                    if isinstance(exc, EmptyPricingPromoteError)
                    else "sandbox_promote_failed"
                )
                # Do not report Claude success when outputs never reached the live bid;
                # otherwise sync validation surfaces as missing hardware_sets/line_items.
                result = runner.RunResult(
                    ok=False,
                    output=result.output,
                    error=f"sandbox promote failed: {exc}",
                    returncode=result.returncode,
                    permanent=True,
                    error_code=error_code,
                )
        if sandbox_ws is not None and promote_ok:
            try:
                await asyncio.to_thread(sandbox_mod.cleanup, str(job["_id"]))
            except Exception:
                log.exception("sandbox cleanup failed for job %s", job["_id"])
        elif sandbox_ws is not None and not promote_ok:
            log.error(
                "sandbox: leaving scratch %s for recovery after promote failure",
                job["_id"],
            )

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
    if project is not None and on_provider is not None:
        await on_provider(project, described)

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
            retry_at=result.retry_at,
        )
        await _record_runmetrics(
            job, recording, prompt, project, described, result.error_code
        )
        return

    try:
        note = await sync(job, project)
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
