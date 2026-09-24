"""USD spend caps checked before a worker claims a job."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from cbc.modules.ops.api.provider import NIM, OLLAMA
from cbc.modules.ops.infrastructure.collections import run_metrics
from cbc.shared import envfile


async def spend_usd(
    *,
    since: datetime,
    project_id: ObjectId | None = None,
    job_types: set[str] | None = None,
) -> float:
    """Sum runMetrics.totalCostUsd since `since` (UTC), billed providers only.

    `totalCostUsd` is whatever the Claude Code CLI reported as `total_cost_usd`,
    and the CLI prices every run off its own Anthropic table - it has no idea the
    request was served by a local model. A NIM leg reading 3.1M cache tokens is
    billed at Anthropic cache-read rates and lands here as $5, so a week of free
    local testing walks the daily cap up until the worker refuses to claim
    anything and every job sits queued with attempts=0.

    Local modes bill nothing, so they are excluded. `provider.supports_subagents`
    and `describe` already treat the same pair as the local ones.
    """
    match: dict[str, Any] = {
        "startedAt": {"$gte": since},
        "totalCostUsd": {"$type": "number"},
        "provider.mode": {"$nin": [OLLAMA, NIM]},
    }
    if project_id is not None:
        # `document_for` writes this with `str(...)`, and the spend page reads it
        # straight out to JSON. Matching the ObjectId found nothing, so the
        # per-project cap never fired either.
        match["projectId"] = str(project_id)
    if job_types is not None:
        match["jobType"] = {"$in": sorted(job_types)}

    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$totalCostUsd"}}},
    ]
    rows = await run_metrics().aggregate(pipeline).to_list(1)
    if not rows:
        return 0.0
    return float(rows[0].get("total") or 0.0)


def _cap(variable: str) -> float | None:
    """Read a cap from the process env, falling back to `.env`.

    Compose does not pass either cap through, so the process env is empty and a
    value written to `.env` used to reach nothing - the cap read as unset and no
    job was ever refused. Every other setting here resolves env -> `.env`
    (`provider.build_env`, `parsing_config.resolve`); this one did not.
    """
    raw = os.environ.get(variable, "").strip()
    if not raw:
        raw = str(envfile.read().get(variable) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def day_cap_usd() -> float | None:
    return _cap("WORKER_MAX_COST_USD_PER_DAY")


def project_cap_usd() -> float | None:
    return _cap("WORKER_MAX_COST_USD_PER_PROJECT")


def caps_enabled() -> bool:
    return day_cap_usd() is not None or project_cap_usd() is not None


async def over_budget(
    *,
    project_id: ObjectId | None,
    claimable_types: set[str] | None = None,
) -> str | None:
    """Return a human reason if spend caps block claiming; else None."""
    day = day_cap_usd()
    project = project_cap_usd()
    if day is None and project is None:
        return None

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    if day is not None:
        spent = await spend_usd(since=since, job_types=claimable_types)
        if spent >= day:
            return f"daily spend ${spent:.2f} >= cap ${day:.2f}"

    if project is not None and project_id is not None:
        spent = await spend_usd(
            since=since, project_id=project_id, job_types=claimable_types
        )
        if spent >= project:
            return (
                f"project spend ${spent:.2f} >= cap ${project:.2f} "
                f"(project {project_id})"
            )
    return None
