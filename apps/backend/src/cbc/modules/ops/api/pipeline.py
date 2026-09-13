"""The pipeline policy other modules read: whether a new bid starts on autopilot."""
from __future__ import annotations

from cbc.modules.ops.infrastructure.collections import settings_collection


async def autopilot_default() -> bool:
    """The admin's default for bids created without an explicit choice."""
    stored = await settings_collection().find_one({"_id": "pipeline"}) or {}
    return bool(stored.get("autopilotDefault", False))
