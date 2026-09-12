"""USD spend caps checked before a worker claims a job."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from cbc.db import db


async def spend_usd(
    *,
    since: datetime,
    project_id: ObjectId | None = None,
    job_types: set[str] | None = None,
) -> float:
    """Sum runMetrics.totalCostUsd since `since` (UTC)."""
    match: dict[str, Any] = {
        "startedAt": {"$gte": since},
        "totalCostUsd": {"$type": "number"},
    }
    if project_id is not None:
        match["projectId"] = project_id
    if job_types is not None:
        match["jobType"] = {"$in": sorted(job_types)}

    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$totalCostUsd"}}},
    ]
    rows = await db.run_metrics.aggregate(pipeline).to_list(1)
    if not rows:
        return 0.0
    return float(rows[0].get("total") or 0.0)


def day_cap_usd() -> float | None:
    raw = os.environ.get("WORKER_MAX_COST_USD_PER_DAY", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def project_cap_usd() -> float | None:
    raw = os.environ.get("WORKER_MAX_COST_USD_PER_PROJECT", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


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
