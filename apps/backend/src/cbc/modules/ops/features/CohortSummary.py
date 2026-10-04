"""GET /api/ops/cohorts - LLM spend grouped by config cohort, from runMetrics. Admin only.

A cohort is ``(jobType, contextHashes minus "prompt")``: the runs that followed the
same prompts, rules, agents, skills, tool profiles, hooks and runtime budget. The
prompt hash embeds the project dir, so keeping it would make every run its own cohort
- it is the one contextHashes field dropped from the key.

The value is the before/after. ``changedFrom`` diffs each cohort against the previous
one of the same job type and names what moved, so "cost fell 41% and the only thing
that changed was that agent" is a sentence this endpoint produces rather than a claim.

Median and mean are computed in Python over ``$push``-ed arrays rather than with
``$percentile``: cohorts are single-digit, and ``$percentile`` would need Mongo 7 for
no gain here.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from cbc.modules.ops.infrastructure.collections import run_metrics
from cbc.shared.auth import require_admin

router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(require_admin)])


@router.get("/cohorts")
async def cohorts(
    jobType: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    return await summary(job_type=jobType, days=days, limit=limit)


def _stats(values: list[Any]) -> dict[str, float]:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    if not nums:
        return {"median": 0.0, "mean": 0.0, "n": 0}
    return {
        "median": round(float(statistics.median(nums)), 6),
        "mean": round(float(statistics.fmean(nums)), 6),
        "n": len(nums),
    }


def _cohort_id(group_id: dict[str, Any]) -> str:
    """Stable digest of the cohort key, computed at read time - no migration."""
    blob = json.dumps(group_id, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _flatten(value: Any, prefix: str, out: dict[str, Any]) -> None:
    """Dotted-path leaves of a nested hash dict, so a diff can name agents.<stem>."""
    if isinstance(value, dict):
        for key, sub in value.items():
            _flatten(sub, f"{prefix}.{key}" if prefix else str(key), out)
    else:
        out[prefix] = value


def _changed_from(older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any] | None:
    """What moved from the older cohort to the newer one, by config key and cost."""
    older_flat: dict[str, Any] = {}
    newer_flat: dict[str, Any] = {}
    _flatten(older.get("context") or {}, "", older_flat)
    _flatten(newer.get("context") or {}, "", newer_flat)
    keys = sorted(
        k
        for k in set(older_flat) | set(newer_flat)
        if older_flat.get(k) != newer_flat.get(k)
    )
    if not keys:
        return None
    delta: dict[str, float] = {}
    prev_cost = older["costUsd"]["median"]
    curr_cost = newer["costUsd"]["median"]
    if prev_cost:
        delta["costUsd"] = round((curr_cost - prev_cost) / prev_cost * 100, 1)
    return {"keys": keys, "deltaPct": delta}


async def summary(*, job_type: str | None = None, days: int = 30, limit: int = 20) -> dict[str, Any]:
    """Cohort roll-up for the ops cohort panel."""
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), 100))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    match: dict[str, Any] = {
        "startedAt": {"$gte": since},
        "totalCostUsd": {"$type": "number"},
    }
    if job_type:
        match["jobType"] = job_type

    pipeline = [
        {"$match": match},
        # Drop `prompt` from the cohort key. $unsetField is Mongo 5.0+; the
        # deployment is Mongo 7. $ifNull guards a doc with no contextHashes.
        {
            "$addFields": {
                "_ctx": {
                    "$unsetField": {
                        "field": "prompt",
                        "input": {"$ifNull": ["$contextHashes", {}]},
                    }
                }
            }
        },
        {
            "$group": {
                "_id": {"jobType": "$jobType", "context": "$_ctx"},
                "runs": {"$sum": 1},
                "costs": {"$push": "$totalCostUsd"},
                "durations": {"$push": "$durationApiMs"},
                "toolCalls": {"$push": "$tools.callCount"},
                "firstRun": {"$min": "$startedAt"},
                "lastRun": {"$max": "$startedAt"},
            }
        },
        {"$sort": {"lastRun": -1}},
        {"$limit": limit},
    ]

    cohorts: list[dict[str, Any]] = []
    async for row in run_metrics().aggregate(pipeline):
        gid = row.get("_id") or {}
        cohorts.append(
            {
                "cohortId": _cohort_id(gid),
                "jobType": gid.get("jobType") or "unknown",
                "context": gid.get("context") or {},
                "runs": int(row.get("runs") or 0),
                "costUsd": _stats(row.get("costs") or []),
                "durationApiMs": _stats(row.get("durations") or []),
                "toolCalls": _stats(row.get("toolCalls") or []),
                "firstRun": row.get("firstRun"),
                "lastRun": row.get("lastRun"),
                "changedFrom": None,
            }
        )

    # changedFrom: within a job type, diff each cohort against the previous
    # (older) one. Sorted newest-first, so cohort[i] is newer than cohort[i+1].
    by_type: dict[str, list[dict[str, Any]]] = {}
    for cohort in cohorts:
        by_type.setdefault(cohort["jobType"], []).append(cohort)
    for group in by_type.values():
        for index in range(len(group) - 1):
            group[index]["changedFrom"] = _changed_from(group[index + 1], group[index])

    return {
        "days": days,
        "since": since.isoformat(),
        "jobType": job_type,
        "cohorts": cohorts,
    }
