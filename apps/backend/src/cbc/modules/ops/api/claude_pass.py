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
import shutil
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

# A wave leg reads a few pages and writes or patches one artifact - far less than a
# whole extraction. Without a per-leg cap, three legs of an extract_bid_set that now
# carries the pipeline budget would each take 200 turns. Size this from a real leg
# recording rather than a guess; the default is a bounded placeholder.
# ponytail: measure it off a .runs leg log once W1 cohorts show the callCount.
WAVE_LEG_MAX_TURNS = int(os.environ.get("WORKER_WAVE_LEG_MAX_TURNS", "80"))

# Tokens one `claude` invocation may spend - input, cache writes and output; cache
# reads are not counted. Like turns it applies per invocation, so per wave leg.
# Turns and wall clock bound how long a run wanders, not what it costs: a pass
# reading page images can spend a day's budget in forty turns.
#
# Set from runMetrics (2026-10, primary-model tokens per leg): extract_bid_set
# p95 567k over 60 runs, max 936k; match_and_price p95 345k over 14, max 456k.
# About twice the p95. The live count covers every model, the recorded one only
# the primary, which the margin also absorbs.
EXTRACT_TOKEN_BUDGET = 1_200_000
MATCH_TOKEN_BUDGET = 700_000
# ponytail: uncalibrated - build_proposal and rerun_extraction had two runs each
# and the rest none. Re-run the runMetrics p95 once they have twenty.
TOKEN_BUDGET = 2_000_000
PIPELINE_TOKEN_BUDGET = 3_000_000
# One budget for every job type when set; "0" turns the budget off.
_TOKEN_BUDGET_OVERRIDE = os.environ.get("WORKER_TOKEN_BUDGET", "").strip()

# (timeout seconds, max turns, max tokens) per job type. Extraction is a multi-phase
# wave on a set that can be 744 pages; the one-phase JOB_TIMEOUT/MAX_TURNS starved
# it, and the pipeline budget it needed used to go only to run_full_pipeline - which
# is retired and refused by the API, so nothing that actually runs received it.
# run_full_pipeline stays in the table because _CLAIM_ALL_EXTRA still claims
# requeued historical jobs.
LIMITS: dict[str, tuple[int, int, int]] = {
    "run_full_pipeline": (PIPELINE_TIMEOUT, PIPELINE_MAX_TURNS, PIPELINE_TOKEN_BUDGET),
    "extract_bid_set": (PIPELINE_TIMEOUT, PIPELINE_MAX_TURNS, EXTRACT_TOKEN_BUDGET),
    "rerun_extraction": (PIPELINE_TIMEOUT, PIPELINE_MAX_TURNS, EXTRACT_TOKEN_BUDGET),
    "match_and_price": (JOB_TIMEOUT, MAX_TURNS, MATCH_TOKEN_BUDGET),
}

# How long the first wave leg gets on its own before the rest follow.
#
# The legs are separate processes but they share a job type - so the same MCP
# schemas - the same cwd and the same CLAUDE.md, which makes their ~32k system
# prefix byte-identical. Prompt caching is server-side and content-keyed, so the
# later legs would read the first one's prefix. Started in the same instant they
# cannot: all three miss, and all three pay to write the same 32k.
#
# Measured on this CLI: a warm prefix cost $0.0056 against $0.0404 cold, 7.2x.
# A few seconds of head start buys that on every leg after the first, against a
# pass that runs for eleven to twenty-one minutes.
WAVE_STAGGER_SECONDS = float(os.environ.get("WORKER_WAVE_STAGGER_SECONDS", "8"))

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


def limits_for(job_type: str) -> tuple[int, int, int]:
    """(timeout seconds, max turns, max tokens) for a job type. 0 tokens is no budget."""
    timeout, turns, tokens = LIMITS.get(job_type, (JOB_TIMEOUT, MAX_TURNS, TOKEN_BUDGET))
    if _TOKEN_BUDGET_OVERRIDE:
        tokens = int(_TOKEN_BUDGET_OVERRIDE)
    return timeout, turns, tokens


def _spent(event: dict[str, Any]) -> tuple[str | None, int]:
    """(message id, tokens it cost) for one assistant event - cache reads excluded."""
    message = event.get("message") or {}
    usage = message.get("usage") or {}
    tokens = sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "cache_creation_input_tokens", "output_tokens")
    )
    return message.get("id"), tokens


# A retry may pick up the session its own leg left behind, and only that one.
RESUME_RETRIES = os.environ.get("WORKER_RESUME_RETRIES", "1").strip() not in ("", "0", "false")

# What the resumed pass is told before its brief is repeated. Without it the leg
# reads its own instruction a second time with no account of why, and starts over
# inside a conversation that already holds the work.
RESUME_PREAMBLE = (
    "The previous attempt at this pass was interrupted - it timed out, was "
    "cancelled, or hit an error. Everything above is your own work from that "
    "attempt.\n\n"
    "Do not start over. Read back what you already established, check which "
    "artifacts you already wrote, and carry on from there. Re-read a page only "
    "if you actually need it again. The brief follows, unchanged.\n\n"
    "---\n\n"
)

# How the CLI reports a session id it cannot open.
_SESSION_GONE = ("no conversation found", "session not found", "no such session")


def _session_gone(outcome: Any) -> bool:
    haystack = f"{getattr(outcome, 'error', '') or ''} {getattr(outcome, 'output', '') or ''}".lower()
    return any(needle in haystack for needle in _SESSION_GONE)


def sessions_from(job: dict[str, Any]) -> dict[str, str]:
    """Session id per leg label from the attempt before this one.

    Empty on a first attempt, so nothing is resumed and behaviour is unchanged.

    Only the *same leg* of the *same job* is resumed. Carrying a session across
    domain jobs was measured and is a losing trade: the take-off leg's
    conversation sits at ~146k tokens per turn, so handing it to pricing adds
    ~$1.17 of cache reads to a job that costs $1.87 - to save the three or four
    turns it spends reading the artifacts. The phases talk to each other through
    files on disk, not through the conversation, which is what makes them cheap
    to start cold and expensive to carry.
    """
    if not RESUME_RETRIES or max(int(job.get("attempts") or 1), 1) < 2:
        return {}
    out: dict[str, str] = {}
    for entry in job.get("waveLegs") or []:
        if isinstance(entry, dict) and entry.get("sessionId"):
            out[str(entry.get("label") or "")] = str(entry["sessionId"])
    return out


async def _record_runmetrics(
    job: dict,
    legs: list["WavePass"],
    recordings: list[Path],
    project: dict | None,
    described: dict | None,
    error_code: str | None = None,
) -> None:
    """Parse the Claude recording(s) after every post-CLI finish(). Never raises.

    A wave is N CLI invocations, each with its own recording, prompt and cost.
    Recording only leg 0 under-reported extraction spend ~Nx, so SpendSummary lied
    and `cost_budget.spend_usd` under-counted - WORKER_MAX_COST_USD_PER_DAY never
    fired. One document per leg now; leg 0 keeps the single-pass id byte-identical,
    and its prompt is the brief that actually ran, not the orchestrator prompt that
    was built and never sent.
    """
    try:
        current = await ops_jobs.get(
            job["_id"],
            {"status": 1, "errorCode": 1, "startedAt": 1, "finishedAt": 1, "provider": 1},
        )
        merged = {**job, **(current or {})}
        for index, (leg, recording) in enumerate(zip(legs, recordings)):
            await runmetrics.record(
                merged,
                recording,
                prompt=leg.prompt,
                project=project,
                provider=described or merged.get("provider"),
                outcome_status=merged.get("status"),
                error_code=error_code or merged.get("errorCode"),
                runtime=limits_for(job["type"]),
                leg=index,
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

    timeout, max_turns, max_tokens = limits_for(job["type"])
    # A wave splits the job's work across legs, each doing a fraction of it, so a
    # leg is capped lower than the whole-job budget the orchestrator path gets.
    leg_max_turns = WAVE_LEG_MAX_TURNS if len(legs) > 1 else max_turns
    worker_id = job.get("workerId", ops_worker.WORKER_ID)
    claim_gen = job.get("claimGeneration", 0)
    # Why every leg should stop, once something says so. Written by the watch
    # below on the loop, read by the legs' threads; the first reason sticks.
    stopped: list[str] = []

    async def watch_cancel() -> None:
        while not stopped:
            # A shutdown stops the subprocess the same way a cancel does. Without
            # this the container's grace period expires mid-run and the job is
            # SIGKILLed into a permanent `running`.
            if ops_worker.stopping():
                stopped.append("worker shutting down")
                return
            try:
                reason = await ops_worker.stop_reason(job["_id"], worker_id, claim_gen)
            except Exception as exc:  # noqa: BLE001 - a missed poll is not a stop
                log.warning("cancel check for job %s failed: %s", job["_id"], exc)
                reason = None
            if reason:
                stopped.append(reason)
                return
            await asyncio.sleep(1)

    from cbc.worker_kit import sandbox as sandbox_mod

    sandbox_ws: Path | None = None
    if project is not None:
        try:
            sandbox_ws = await asyncio.to_thread(
                sandbox_mod.prepare, project["slug"]
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

    prior_sessions = sessions_from(job)

    def run_leg(leg: WavePass, leg_recording: Path):
        resume = prior_sessions.get(leg.label or "")

        def _go(session: str | None, prompt: str):
            # Per invocation, like turns. stream-json re-emits a message as it
            # streams, each copy with the same usage, so it is counted by id.
            spent: dict[str, int] = {}

            def on_event(event: dict[str, Any]) -> None:
                message_id, tokens = _spent(event)
                spent[message_id or f"_event{len(spent)}"] = tokens

            def cancel_check() -> str | None:
                if stopped:
                    return stopped[0]
                total = sum(spent.values())
                if max_tokens and total > max_tokens:
                    return f"token budget exceeded ({total} > {max_tokens})"
                return None

            kwargs = dict(
                prompt=prompt,
                timeout=timeout,
                env=env,
                redact_values=provider.secret_values(config),
                recording=leg_recording,
                job_type=job["type"],
                max_turns=leg_max_turns,
                cancel_check=cancel_check,
                settings=provider.claude_settings_overlay(config),
                on_heartbeat=ping,
                heartbeat_seconds=ops_worker.HEARTBEAT_SECONDS,
                cwd=sandbox_ws,
                resume_session_id=session,
            )
            if sandbox_mod.mode() == "docker":
                # Named per claim, so a re-claimed job's container never collides
                # with the one its reaped predecessor is still stopping.
                name = f"cbc-{job['_id']}-g{claim_gen}-{leg.label or 'main'}"
                return sandbox_mod.run_claude_docker(**kwargs, container_name=name)
            return runner.run_claude(**kwargs, on_event=on_event)

        if not resume:
            return _go(None, leg.prompt)

        log.info(
            "%s%s: resuming session %s from the previous attempt",
            job["type"], f" [{leg.label}]" if leg.label else "", resume,
        )
        outcome = _go(resume, RESUME_PREAMBLE + leg.prompt)
        if outcome.ok or not _session_gone(outcome):
            return outcome
        # The session store is keyed on the working directory and lives outside
        # it, so it normally survives the sandbox being rebuilt - but a pruned
        # store, a changed cwd or a different host all lose it. Falling back to a
        # cold run costs what a retry used to cost; failing here would cost the
        # whole job, which is strictly worse than not having resumed at all.
        log.warning(
            "%s%s: session %s is gone, retrying cold (%s)",
            job["type"], f" [{leg.label}]" if leg.label else "", resume, outcome.error,
        )
        return _go(None, leg.prompt)

    watcher = asyncio.create_task(watch_cancel())
    heartbeat = asyncio.create_task(
        ops_worker.beat(job["_id"], worker_id, claim_gen)
    )
    progress_watcher = asyncio.create_task(watch_progress_bound())
    result = None
    leg_results: list[runner.RunResult] = []
    wave_leg_records: list[dict[str, Any]] = []
    try:
        if len(legs) == 1:
            result = await asyncio.to_thread(run_leg, legs[0], recordings[0])
            leg_results = [result]
        else:
            # Started in one gather, so they overlap rather than queue. They share
            # one sandbox and write different files; the single promote below
            # copies all of it back with nothing to reconcile.
            log.info(
                "%s wave: starting %s concurrently, %ss apart so they share a prefix",
                job["type"],
                ", ".join(leg.label for leg in legs),
                WAVE_STAGGER_SECONDS,
            )
            async def staggered(leg, path, delay: float):
                # Only the first leg needs a head start. The rest can go together
                # once the prefix exists - concurrent cache *reads* are fine; it
                # is concurrent first-writes that all miss.
                if delay:
                    await asyncio.sleep(delay)
                return await asyncio.to_thread(run_leg, leg, path)

            leg_results = list(
                await asyncio.gather(
                    *(
                        staggered(leg, path, 0 if index == 0 else WAVE_STAGGER_SECONDS)
                        for index, (leg, path) in enumerate(zip(legs, recordings))
                    )
                )
            )
            result = _combine(legs, leg_results)
    finally:
        # A pass torn down by an exception or a task cancel still has leg threads
        # running claude; give them a reason so they stop rather than finish alone.
        if not stopped:
            stopped.append("pass ended")
        watcher.cancel()
        heartbeat.cancel()
        progress_watcher.cancel()
        promote_ok = True
        # A wave is not all-or-nothing on the artifacts: each leg that finished
        # wrote its own file. If some legs failed, promote just the succeeded
        # ones' artifacts - a failed FRP leg must not discard a finished take-off.
        # The job still fails and retries; the retry re-clones from a live bid
        # that now holds the succeeded work and skips those legs.
        wave_only: set[str] | None = None
        # Recorded for a single pass too, not just a wave. A one-leg job carries
        # the label "" and is the case a retry most needs: match_and_price and
        # build_proposal have no wave to skip forward through, so without the
        # session id their retry is a cold start over the whole job.
        wave_leg_records = [
            {
                "label": leg.label,
                "ok": bool(res.ok),
                "error": res.error,
                "sessionId": res.session_id,
            }
            for leg, res in zip(legs, leg_results)
        ]
        if len(legs) > 1:
            if result is not None and not result.ok:
                wave_only = {
                    prompts.WAVE_LEGS[leg.label]["artifact"]
                    for leg, res in zip(legs, leg_results)
                    if res.ok and leg.label in prompts.WAVE_LEGS
                }
        full_promote = (
            sandbox_ws is not None
            and project is not None
            and result is not None
            and result.ok
        )
        partial_promote = (
            sandbox_ws is not None
            and project is not None
            and result is not None
            and not result.ok
            and bool(wave_only)
        )
        if full_promote:
            try:
                await asyncio.to_thread(sandbox_mod.promote, project["slug"])
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
        elif partial_promote:
            # Best-effort: the job has already failed and will retry. A failure to
            # promote the succeeded legs only means the retry re-runs them too.
            try:
                await asyncio.to_thread(
                    sandbox_mod.promote, project["slug"], only=wave_only
                )
            except Exception:
                log.exception(
                    "sandbox partial-wave promote failed for job %s", job["_id"]
                )
        if sandbox_ws is not None and project is not None and promote_ok:
            try:
                await asyncio.to_thread(sandbox_mod.cleanup, project["slug"])
            except Exception:
                log.exception("sandbox cleanup failed for job %s", job["_id"])
        elif sandbox_ws is not None and project is not None and not promote_ok:
            # The scratch root is keyed by project now, so the next job on this
            # bid would wipe the only copy of work that never reached it. Move
            # it aside instead.
            # ponytail: never swept, add one if promote failures become routine.
            kept = sandbox_mod.quarantine_dir(project["slug"], str(job["_id"]))
            try:
                await asyncio.to_thread(shutil.move, str(sandbox_ws), str(kept))
                log.error("sandbox: kept %s for recovery after promote failure", kept)
            except Exception:
                log.exception(
                    "sandbox: could not set aside %s after promote failure", sandbox_ws
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
    provider_fields: dict[str, Any] = {"provider": described}
    if wave_leg_records:
        # Per-leg outcome, so a retry can skip the legs that already succeeded
        # (extraction_wave reads this) and an operator can see which leg failed.
        provider_fields["waveLegs"] = wave_leg_records
    await ops_jobs.set_fields(job["_id"], provider_fields)
    if project is not None and on_provider is not None:
        await on_provider(project, described)

    recording_note = ""
    notes: list[str] = []
    for rec in recordings:
        if not rec.exists():
            continue
        try:
            raw = await asyncio.to_thread(
                rec.read_text, encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        notes.extend(streaming.recording_warnings(raw))
    if notes:
        recording_note = "; ".join(notes)
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
            job, legs, recordings, project, described, result.error_code
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
            job, legs, recordings, project, described, "artifact_validation"
        )
        return
    except Exception as exc:  # a sync failure is a real failure - do not mask it
        if str(exc) == "cancelled by estimator":
            await finish(job, False, "cancelled by estimator", result.output)
            await _record_runmetrics(job, legs, recordings, project, described)
            return
        await finish(job, False, f"result sync failed: {exc}", result.output, error_code="sync_failed")
        await _record_runmetrics(
            job, legs, recordings, project, described, "sync_failed"
        )
        return

    combined = note
    if recording_note:
        combined = f"{note}; {recording_note}" if note else recording_note
    await finish(job, True, None, result.output, combined or None)
    await _record_runmetrics(job, legs, recordings, project, described)
