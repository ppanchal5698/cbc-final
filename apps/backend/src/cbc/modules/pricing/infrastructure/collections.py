"""The collections pricing owns, and the indexes it builds on them.

No other module may name these. referenceDataRevisions is written by
reference_store when a family is replaced, and has never had indexes of its own.
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from cbc.persistence import names
from cbc.shared.mongo import database


def reference_data():
    """Curated reference-library documents (margins, tax, tiers, …)."""
    return database()[names.REFERENCE_DATA]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations; then seeds any family the database lacks."""
    await reference_data().create_index([("family", ASCENDING)], unique=True)
    await reference_data().create_index([("updatedAt", DESCENDING)])
    from cbc.modules.pricing.api.reference_store import ensure_reference_seed

    await ensure_reference_seed()
