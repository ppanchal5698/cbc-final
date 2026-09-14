"""The collections extraction owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.extraction.api`.
"""
from __future__ import annotations

import logging
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from cbc.shared.persistence import names
from cbc.shared.mongo import database, replace_index

log = logging.getLogger("cbc.api.db")  # where catalog's index messages already go


def openings():
    return database()[names.OPENINGS]


def failed_extractions():
    """Claude payloads that failed the schema gate, kept for operators."""
    return database()[names.FAILED_EXTRACTIONS]


def takeoffs():
    """FR-12 - FRP geometry (§3.24)."""
    return database()[names.TAKEOFFS]


def feedback_events():
    """FR-13 - every estimator correction, structured (§3.31)."""
    return database()[names.FEEDBACK_EVENTS]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, like every module's."""
    await openings().create_index([("projectId", ASCENDING), ("status", ASCENDING)])
    # Two openings with one door number on a bid make this unique index unbuildable.
    # That raised out of startup, so a single dirty bid stopped the API; migration 4
    # only logged it. Report it, as catalog does for products, and keep serving -
    # the identity is not enforced until the duplicates are merged.
    try:
        await replace_index(
            openings(),
            "opening_door_identity",
            [("orgId", ASCENDING), ("projectId", ASCENDING), ("doorNumber", ASCENDING)],
            unique=True,
            partialFilterExpression={
                "doorNumber": {"$exists": True, "$type": "string"},
            },
        )
    except DuplicateKeyError as exc:
        log.error(
            "openings holds two rows with the same bid and door number, so the "
            "opening_door_identity index could not be built and door identity is not "
            "enforced. Merge them (group openings by orgId, projectId, doorNumber) and "
            "restart. %s",
            exc.details.get("keyValue") if exc.details else exc,
        )
    # Legacy non-unique mark lookup kept for list screens that still sort by mark.
    await openings().create_index([("projectId", ASCENDING), ("mark", ASCENDING)])
    await failed_extractions().create_index(
        [("projectId", ASCENDING), ("createdAt", DESCENDING)]
    )
    await failed_extractions().create_index([("jobId", ASCENDING)])
    # Alternates are queried per group on both the extraction and quote screens.
    await openings().create_index([("projectId", ASCENDING), ("alternateGroup", ASCENDING)])


async def delete_for_project(project_id: Any) -> None:
    """A bid is being deleted: its openings go with it."""
    await openings().delete_many({"projectId": project_id})
