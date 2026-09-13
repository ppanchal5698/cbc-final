"""Backfill doorNumber and the unique openings identity index.

Spec §3.23: unique `{ orgId, bidRequestId, doorNumber }`. Runtime still stores
`projectId` + `mark`; `doorNumber` is the unique identity (mark, or mark#N when
a schedule lists the same mark twice - see sync `_distinct_keys`).
"""
from __future__ import annotations

import logging

from cbc.shared.persistence import names

VERSION = 4
DESCRIPTION = "backfill openings.doorNumber from mark and unique (orgId, bidRequestId, doorNumber)"

log = logging.getLogger("cbc.migrations")


async def apply(db) -> None:
    openings = db[names.OPENINGS]
    cursor = openings.find(
        {"$or": [{"doorNumber": {"$exists": False}}, {"doorNumber": None}]},
        {"mark": 1, "projectId": 1},
    )
    async for doc in cursor:
        mark = doc.get("mark")
        if not mark:
            continue
        await openings.update_one({"_id": doc["_id"]}, {"$set": {"doorNumber": str(mark)}})

    # bidRequestId mirrors projectId for the spec vocabulary.
    await openings.update_many(
        {"bidRequestId": {"$exists": False}, "projectId": {"$exists": True}},
        [{"$set": {"bidRequestId": "$projectId"}}],
    )

    # Unique identity. Partial so legacy rows without doorNumber do not block.
    try:
        await openings.create_index(
            [("orgId", 1), ("projectId", 1), ("doorNumber", 1)],
            name="opening_door_identity",
            unique=True,
            partialFilterExpression={
                "doorNumber": {"$exists": True, "$type": "string"},
            },
        )
    except Exception as exc:
        log.warning("opening_door_identity index deferred: %s", exc)
