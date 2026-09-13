"""The collections quoting owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.quoting.api`.
"""
from __future__ import annotations

from typing import Any

from pymongo import ASCENDING

from cbc.shared.persistence import names
from cbc.shared.mongo import database


def estimate_lines():
    return database()[names.ESTIMATE_LINES]


def quotes():
    return database()[names.QUOTES]


def proposals():
    return database()[names.PROPOSALS]


def vendor_rfqs():
    """FR-16 - the third cost path (§3.28)."""
    return database()[names.VENDOR_RFQS]


def rfis():
    """Phase 5 questions raised before finalizing (§3.29)."""
    return database()[names.RFIS]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, like every module's."""
    await estimate_lines().create_index([("projectId", ASCENDING), ("division", ASCENDING)])
    await quotes().create_index([("projectId", ASCENDING)], unique=True)
    await proposals().create_index([("projectId", ASCENDING)])
    # Alternates are queried per group on both the extraction and quote screens.
    await estimate_lines().create_index([("projectId", ASCENDING), ("alternateGroup", ASCENDING)])


async def delete_for_project(project_id: Any) -> None:
    """A bid is being deleted: its quote lines, quote and proposal go with it.

    RFQs and RFIs stay, as they always have - the cascade never named them.
    """
    await estimate_lines().delete_many({"projectId": project_id})
    await quotes().delete_many({"projectId": project_id})
    await proposals().delete_many({"projectId": project_id})
