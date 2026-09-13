"""The collections projects owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.projects.api`.
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from cbc.shared.persistence import names
from cbc.shared.mongo import database


def bid_requests():
    return database()[names.BID_REQUESTS]


def calls():
    return database()[names.CALLS]


def counters():
    """Monotonic sequences. `_id` is the counter name, `seq` is the value."""
    return database()[names.COUNTERS]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, like every module's."""
    await bid_requests().create_index([("code", ASCENDING)], unique=True)
    await bid_requests().create_index([("slug", ASCENDING)], unique=True)
    await bid_requests().create_index([("stage", ASCENDING), ("bidDue", ASCENDING)])
    await calls().create_index([("projectId", ASCENDING), ("createdAt", DESCENDING)])
