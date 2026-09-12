"""Cross-domain autopilot orchestration.

Replaces the former single-session `run_full_pipeline` job. Platform (or an
autopilot upload) starts the chain with `extract_bid_set` and
`payload.orchestrate=true`. When that job finishes successfully, the next domain
job is enqueued, and so on through match_and_price â†’ build_proposal.
"""
from __future__ import annotations

import logging
from typing import Any

from cbc.services import jobs as job_service
from cbc.services.domains import ORCHESTRATED_CHAIN

__all__ = ["ORCHESTRATED_CHAIN", "enqueue_autopilot", "maybe_continue_chain", "next_in_chain"]

log = logging.getLogger("cbc.orchestrator")


def next_in_chain(job_type: str) -> str | None:
    try:
        idx = ORCHESTRATED_CHAIN.index(job_type)
    except ValueError:
        return None
    if idx + 1 >= len(ORCHESTRATED_CHAIN):
        return None
    return ORCHESTRATED_CHAIN[idx + 1]


async def enqueue_autopilot(
    project_id: Any,
    *,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
    delay_seconds: int = 0,
) -> dict[str, Any]:
    """Start the domain chain at extract_bid_set."""
    body = dict(payload or {})
    body["orchestrate"] = True
    return await job_service.enqueue_exclusive(
        "extract_bid_set",
        project_id,
        payload=body,
        actor=actor,
        delay_seconds=delay_seconds,
    )


async def maybe_continue_chain(job: dict[str, Any]) -> dict[str, Any] | None:
    """If this successful job was orchestrated, enqueue the next domain step."""
    payload = job.get("payload") or {}
    if not payload.get("orchestrate"):
        return None
    nxt = next_in_chain(job["type"])
    if not nxt:
        log.info("orchestrate chain complete after %s", job["type"])
        return None
    project_id = job.get("projectId")
    if project_id is None:
        log.warning("orchestrate job %s has no projectId; cannot continue", job["type"])
        return None

    from cbc.db import db
    from cbc.services import chain

    project = await db.projects.find_one({"_id": project_id}, {"chainState": 1, "autopilot": 1})
    chain_state = (project or {}).get("chainState")
    if (project or {}).get("autopilot") is False:
        log.info("orchestrate skipped after %s: autopilot is off", job["type"])
        return None
    if not chain.can_advance(job["type"], chain_state):
        log.info(
            "orchestrate skipped after %s: chainState=%s",
            job["type"],
            chain_state,
        )
        return None

    # Carry orchestrate + any document context forward.
    forward = {k: v for k, v in payload.items() if k != "version"}
    forward["orchestrate"] = True
    forward["previousJobType"] = job["type"]
    log.info("orchestrate: enqueue %s after %s", nxt, job["type"])
    try:
        queued = await job_service.enqueue_exclusive(
            nxt,
            project_id,
            payload=forward,
            actor=payload.get("actor") or job.get("createdBy") or "system",
        )
    except job_service.PipelineJobActive as exc:
        log.warning(
            "orchestrate blocked after %s: another pipeline job is active (%s)",
            job["type"],
            exc.active.get("type"),
        )
        await chain.set_state(
            project_id,
            "awaiting_manual_retry",
            detail=(
                f"Could not start {nxt}: a {exc.active.get('type')} job is "
                "still active. Stage stays at the last successful pass."
            ),
        )
        return None
    start = chain.START_STATE.get(nxt)
    if start:
        await chain.set_state(project_id, start)
    return queued

