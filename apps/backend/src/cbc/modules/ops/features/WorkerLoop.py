"""The job worker: claim queued jobs, run them, recover the ones a dead worker held.

    python -m cbc.worker              # run the loop
    python -m cbc.worker --once       # process at most one job, then exit
    python -m cbc.worker --preflight  # check the Claude CLI is usable

This is the queue side. What runs a claimed job - a job slice in the module that
owns it - is registered through cbc.modules.ops.api.worker by the worker's
composition root, cbc/worker/main.py.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from datetime import datetime, timedelta, timezone

from cbc.core import claude_cli as runner
from cbc.modules.ops.api import audit, provider, worker as ops_worker
from cbc.modules.ops.api.worker import HEARTBEAT_SECONDS, MAX_ATTEMPTS, WORKER_ID
from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection

log = logging.getLogger("cbc.worker")


POLL_SECONDS = int(os.environ.get("WORKER_POLL_SECONDS", "5"))


def concurrency_for(raw: str | None = None) -> int:
    """How many jobs this process may run at once. Default 1; junk and 0 become 1."""
    value = os.environ.get("WORKER_CONCURRENCY", "1") if raw is None else raw
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


DEFAULT_STALE_AFTER = HEARTBEAT_SECONDS * 6
STALE_AFTER = DEFAULT_STALE_AFTER  # compat alias for the non-extract window
EXTRACT_JOB_TYPES = frozenset({"extract_bid_set", "rerun_extraction", "run_full_pipeline"})


def stale_after_for(job_type: str) -> int:
    """Seconds without a heartbeat before this job type is considered abandoned."""
    if job_type in EXTRACT_JOB_TYPES:
        raw = os.environ.get("WORKER_EXTRACT_STALE_AFTER_SECONDS", "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
        return max(600, DEFAULT_STALE_AFTER)
    raw = os.environ.get("WORKER_STALE_AFTER_SECONDS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_STALE_AFTER


# Which job types a worker started with WORKER_DOMAIN=<domain> claims.
DOMAIN_JOB_TYPES: dict[str, frozenset[str]] = {
    "intake": frozenset({"ingest_addendum"}),
    "extraction": frozenset({"extract_bid_set", "rerun_extraction"}),
    "pricing": frozenset({"match_and_price"}),
    "quoting": frozenset({"build_proposal"}),
    "catalog": frozenset({"index_catalog", "delete_catalog", "ingest_pricebook"}),
}


def claimable_types(domain: str) -> frozenset[str]:
    try:
        return DOMAIN_JOB_TYPES[domain]
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain}") from exc


# Domain filter: set WORKER_DOMAIN (intake|extraction|pricing|quoting|catalog).
# Empty / unset = claim nothing (fail closed) unless WORKER_CLAIM_ALL=1 for legacy.
def _claimable() -> frozenset[str] | None:
    if os.environ.get("WORKER_CLAIM_ALL", "").strip() in {"1", "true", "yes"}:
        return None
    domain = os.environ.get("WORKER_DOMAIN", "").strip()
    if not domain:
        raise RuntimeError(
            "WORKER_DOMAIN must be set to a domain name "
            "(intake, extraction, pricing, quoting, catalog), "
            "or set WORKER_CLAIM_ALL=1"
        )
    return claimable_types(domain)


CLAIMABLE_TYPES = _claimable()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def claim() -> dict | None:
    """Atomically take the oldest due job this domain may run.

    When WORKER_MAX_COST_USD_* caps are set, peek candidates oldest-first and
    skip (leave queued) any whose project/day spend is already at cap so a
    blocked bid does not starve the rest of the queue.
    """
    now = _now()
    base_query: dict = {
        "status": "queued",
        "$or": [{"nextAttemptAt": None}, {"nextAttemptAt": {"$lte": now}}],
    }
    if CLAIMABLE_TYPES is not None:
        base_query["type"] = {"$in": sorted(CLAIMABLE_TYPES)}

    from cbc.modules.ops.api import cost_budget

    if not cost_budget.caps_enabled():
        return await jobs_collection().find_one_and_update(
            base_query,
            {
                "$set": {
                    "status": "running",
                    "startedAt": now,
                    "heartbeatAt": now,
                    "workerId": WORKER_ID,
                },
                "$inc": {"attempts": 1, "claimGeneration": 1},
            },
            sort=[("createdAt", 1)],
            return_document=True,
        )

    skipped: list = []
    alerted = False
    while True:
        query = dict(base_query)
        if skipped:
            query["_id"] = {"$nin": skipped}
        candidate = await jobs_collection().find_one(query, sort=[("createdAt", 1)])
        if candidate is None:
            return None
        reason = await cost_budget.over_budget(
            project_id=candidate.get("projectId"),
            claimable_types=CLAIMABLE_TYPES,
        )
        if reason:
            log.warning(
                "cost budget blocked claim of job %s (%s): %s",
                candidate.get("_id"),
                candidate.get("type"),
                reason,
            )
            if not alerted:
                alerted = True
                try:
                    from cbc.modules.ops.api import alerts

                    alerts.notify(
                        f"Worker cost budget blocked claim: {reason}",
                        extra={
                            "jobId": str(candidate.get("_id")),
                            "jobType": candidate.get("type"),
                            "projectId": str(candidate["projectId"])
                            if candidate.get("projectId")
                            else None,
                        },
                    )
                except Exception:
                    log.exception("cost-budget alert failed")
            skipped.append(candidate["_id"])
            # Day cap blocks every job — no point scanning further.
            if cost_budget.day_cap_usd() is not None and "daily spend" in reason:
                return None
            continue

        claimed = await jobs_collection().find_one_and_update(
            {**base_query, "_id": candidate["_id"]},
            {
                "$set": {
                    "status": "running",
                    "startedAt": now,
                    "heartbeatAt": now,
                    "workerId": WORKER_ID,
                },
                "$inc": {"attempts": 1, "claimGeneration": 1},
            },
            return_document=True,
        )
        if claimed is not None:
            return claimed
        # Lost the race; try the next candidate.
        skipped.append(candidate["_id"])


async def reap_abandoned() -> int:
    """Recover jobs whose worker died while holding them.

    A `running` job with a stale heartbeat is not running: the process that
    claimed it is gone. Left alone it stays `running` forever, and because the
    exclusive-active-job index counts it as in flight, every later job of that
    type for that bid is silently handed back this corpse instead of being
    queued - the bid can never be re-extracted through the UI again.

    claimGeneration is the fencing token: reaping increments it so a late
    sync from the dead worker cannot commit.
    """
    now = _now()
    min_window = min(
        stale_after_for(kind)
        for kind in (
            "extract_bid_set",
            "match_and_price",
            "build_proposal",
            "ingest_addendum",
            "index_catalog",
            "ingest_pricebook",
        )
    )
    cutoff = now - timedelta(seconds=min_window)
    abandoned = await jobs_collection().find(
        {
            "status": "running",
            "$or": [{"heartbeatAt": {"$lte": cutoff}}, {"heartbeatAt": None}],
        }
    ).to_list(100)

    reaped = 0
    while abandoned:
        for job in abandoned:
            if not _heartbeat_stale(job, now):
                continue
            attempts = job.get("attempts", 1)
            retry = attempts < MAX_ATTEMPTS
            terminal = "queued" if retry else "dead"
            result = await jobs_collection().update_one(
                {
                    "_id": job["_id"],
                    "status": "running",
                    "claimGeneration": job.get("claimGeneration"),
                },
                {
                    "$set": {
                        "status": terminal,
                        "error": "worker stopped while this job was running",
                        "nextAttemptAt": now if retry else None,
                        "heartbeatAt": None,
                        "workerId": None,
                        "finishedAt": None if retry else now,
                    },
                    "$inc": {"claimGeneration": 1},
                },
            )
            if not result.matched_count:
                continue
            reaped += 1
            await audit.record(
                f"job.reaped.{job['type']}",
                actor="worker",
                target={"jobId": job["_id"], "projectId": job.get("projectId")},
                note="requeued" if retry else "attempts exhausted",
            )
            log.warning(
                "reaped abandoned %s (attempt %s) - %s",
                job["type"], attempts, "requeued" if retry else "dead-lettered",
            )
            if not retry:
                await ops_worker.dead_letter(job, "worker stopped while this job was running")
        if len(abandoned) < 100:
            break
        abandoned = await jobs_collection().find(
            {
                "status": "running",
                "$or": [{"heartbeatAt": {"$lte": cutoff}}, {"heartbeatAt": None}],
            }
        ).to_list(100)
    return reaped


def _heartbeat_stale(job: dict, now: datetime) -> bool:
    beat = job.get("heartbeatAt")
    if beat is None:
        return True
    if getattr(beat, "tzinfo", None) is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return beat <= now - timedelta(seconds=stale_after_for(job.get("type") or ""))


async def process(job: dict) -> None:
    """Run one claimed job with the handler registered for its type."""
    await ops_worker.run(job)


async def loop(once: bool = False) -> int:
    # The catalog server reads the page index from MongoDB with a credential that
    # cannot write, handed to it per job by cbc.core.toolsets. Say so if there is
    # none, because a pricing pass with no catalog flags every line MANUAL and
    # looks like a model failure rather than a missing credential.
    from cbc.shared.mongo import readonly_uri
    from cbc.shared import otel

    otel.configure(os.environ.get("OTEL_SERVICE_NAME") or "cbc.worker")

    derived = readonly_uri()
    if derived and not os.environ.get("MONGODB_READONLY_URI"):
        # toolsets.config_for reads the env; derive the local-dev URI once here
        # so core stays free of the Mongo client.
        os.environ["MONGODB_READONLY_URI"] = derived

    if not derived:
        log.warning(
            "no read-only MongoDB credential; the catalog server will not be able "
            "to read the page index and pricing will fall back to manual entry"
        )

    log.info(
        "worker up - polling every %ss (concurrency %s)",
        POLL_SECONDS,
        1 if once else concurrency_for(),
    )
    await reap_abandoned()

    slots = 1 if once else concurrency_for()
    in_flight: set[asyncio.Task] = set()

    async def run_claimed(job: dict) -> None:
        try:
            await process(job)
        except Exception as exc:
            # Without this, one unexpected exception ends the worker with the
            # job still marked `running` - which the reaper would eventually
            # recover, but only after the container came back. Record it now.
            log.exception("job %s raised", job["type"])
            try:
                await ops_worker.finish(job, False, f"worker error: {exc}", "")
            except Exception:
                log.exception("could not record the failure for job %s", job["_id"])

    while not ops_worker._stop.is_set():
        while len(in_flight) < slots and not ops_worker._stop.is_set():
            job = await claim()
            if not job:
                break
            in_flight.add(asyncio.create_task(run_claimed(job)))
            if once:
                break
        if in_flight:
            _done, in_flight = await asyncio.wait(
                in_flight, return_when=asyncio.FIRST_COMPLETED
            )
            if once:
                return 0
            continue
        if once:
            log.info("no queued jobs")
            return 0
        await reap_abandoned()
        try:
            await asyncio.wait_for(ops_worker._stop.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    if in_flight:
        await asyncio.wait(in_flight)
    log.info("worker stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--preflight", action="store_true", help="check the Claude CLI")
    args = parser.parse_args()

    if args.preflight:
        # Against the configured provider, not the shell that happens to be
        # running this. Checking the inherited environment reports a failure on a
        # correctly configured system, which is worse than not checking at all.
        async def check() -> tuple[str | None, dict]:
            config = await ops_worker.claude_config()
            env, _ = provider.build_env(config)
            problem = await asyncio.to_thread(
                runner.preflight,
                env,
                provider.secret_values(config),
                provider.claude_settings_overlay(config),
            )
            return problem, provider.describe(config)

        problem, described = asyncio.run(check())
        if problem:
            print(f"PREFLIGHT FAILED ({described['mode']}): {problem}")
            return 1
        print(
            f"PREFLIGHT OK - {described['mode']} / {described['model']}; "
            "Claude Code is reachable and authenticated."
        )
        for warning in described.get("warnings", []):
            print(f"PREFLIGHT WARN - {warning}")
        return 0

    if not ops_worker.bound():
        raise RuntimeError("no job handlers registered; start the worker with `python -m cbc.worker`")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: ops_worker._stop.set())
        except (ValueError, OSError):  # not available on every platform/thread
            pass

    return asyncio.run(loop(args.once))
