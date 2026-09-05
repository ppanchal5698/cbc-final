"""Operator spend rollup from runMetrics (not queue depth)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cbc.db import db
from cbc.services import cost_budget


def _cache_hit_ratio(tokens: dict[str, Any] | None) -> float | None:
    tokens = tokens or {}
    cache_read = float(tokens.get("cacheRead") or 0)
    cache_create = float(tokens.get("cacheCreate") or 0)
    denom = cache_read + cache_create
    if denom <= 0:
        return None
    return cache_read / denom


async def summary(*, hours: int = 24, recent_limit: int = 50) -> dict[str, Any]:
    """Aggregate LLM spend for the ops spend page."""
    hours = max(1, min(int(hours), 168))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    match = {
        "startedAt": {"$gte": since},
        "totalCostUsd": {"$type": "number"},
    }

    total_rows = await db.run_metrics.aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "totalCostUsd": {"$sum": "$totalCostUsd"},
                    "runs": {"$sum": 1},
                }
            },
        ]
    ).to_list(1)
    total_cost = float(total_rows[0]["totalCostUsd"]) if total_rows else 0.0
    runs = int(total_rows[0]["runs"]) if total_rows else 0

    by_type: list[dict[str, Any]] = []
    async for row in db.run_metrics.aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": "$jobType",
                    "totalCostUsd": {"$sum": "$totalCostUsd"},
                    "runs": {"$sum": 1},
                }
            },
            {"$sort": {"totalCostUsd": -1}},
        ]
    ):
        by_type.append(
            {
                "jobType": row["_id"] or "unknown",
                "totalCostUsd": float(row["totalCostUsd"] or 0),
                "runs": int(row["runs"] or 0),
            }
        )

    by_project: list[dict[str, Any]] = []
    project_cap = cost_budget.project_cap_usd()
    async for row in db.run_metrics.aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": {
                        "projectId": "$projectId",
                        "projectSlug": "$projectSlug",
                    },
                    "totalCostUsd": {"$sum": "$totalCostUsd"},
                    "runs": {"$sum": 1},
                }
            },
            {"$sort": {"totalCostUsd": -1}},
            {"$limit": 50},
        ]
    ):
        spent = float(row["totalCostUsd"] or 0)
        key = row["_id"] or {}
        by_project.append(
            {
                "projectId": key.get("projectId"),
                "projectSlug": key.get("projectSlug"),
                "totalCostUsd": spent,
                "runs": int(row["runs"] or 0),
                "overProjectCap": bool(
                    project_cap is not None and spent >= project_cap
                ),
            }
        )

    recent_docs = (
        await db.run_metrics.find(match)
        .sort([("startedAt", -1)])
        .limit(recent_limit)
        .to_list(recent_limit)
    )
    recent = [
        {
            "id": doc.get("_id"),
            "jobId": doc.get("jobId"),
            "jobType": doc.get("jobType"),
            "projectId": doc.get("projectId"),
            "projectSlug": doc.get("projectSlug"),
            "totalCostUsd": float(doc["totalCostUsd"])
            if isinstance(doc.get("totalCostUsd"), (int, float))
            else None,
            "cacheHitRatio": _cache_hit_ratio(doc.get("tokens")),
            "startedAt": doc.get("startedAt"),
            "finishedAt": doc.get("finishedAt"),
        }
        for doc in recent_docs
    ]

    day_cap = cost_budget.day_cap_usd()
    return {
        "windowHours": hours,
        "since": since.isoformat(),
        "totalCostUsd": total_cost,
        "runs": runs,
        "dailyCapUsd": day_cap,
        "projectCapUsd": project_cap,
        "overDailyCap": bool(day_cap is not None and total_cost >= day_cap),
        "byType": by_type,
        "byProject": by_project,
        "recent": recent,
    }
