"""Convert runMetrics timestamps from ISO strings to real Dates.

`document_for` used to write `startedAt` / `finishedAt` with `.isoformat()`.
Mongo keeps String and Date in separate BSON type brackets, so every
`{"startedAt": {"$gte": <datetime>}}` matched nothing. That silently disabled
both readers of this collection: the spend page reported zeros, and
`cost_budget.spend_usd` summed to 0.0 - so WORKER_MAX_COST_USD_PER_DAY and
WORKER_MAX_COST_USD_PER_PROJECT never fired, on a pipeline whose cost was the
problem being investigated.

The writer now stores Dates. This brings the rows already on disk with it, so
the indexes on `(jobType, startedAt)` and `(projectId, startedAt)` can serve a
range rather than scanning past a type mismatch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from cbc.shared.persistence import names

VERSION = 6
DESCRIPTION = "runMetrics.startedAt/finishedAt from ISO string to Date"

log = logging.getLogger("cbc.migrations")


def _as_date(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def apply(db) -> None:
    metrics = db[names.RUN_METRICS]
    converted = 0
    unreadable = 0
    cursor = metrics.find(
        {"$or": [{"startedAt": {"$type": "string"}}, {"finishedAt": {"$type": "string"}}]},
        {"startedAt": 1, "finishedAt": 1},
    )
    async for doc in cursor:
        update: dict[str, datetime] = {}
        for field in ("startedAt", "finishedAt"):
            if not isinstance(doc.get(field), str):
                continue
            moment = _as_date(doc.get(field))
            if moment is None:
                unreadable += 1
                continue
            update[field] = moment
        if update:
            await metrics.update_one({"_id": doc["_id"]}, {"$set": update})
            converted += 1

    if converted or unreadable:
        log.info(
            "runMetrics timestamps: %s document(s) converted to Date, %s value(s) unparseable",
            converted,
            unreadable,
        )
