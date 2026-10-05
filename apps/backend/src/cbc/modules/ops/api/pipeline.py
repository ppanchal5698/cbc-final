"""The pipeline policy other modules read: whether a new bid starts on autopilot,
and which engine prices it."""
from __future__ import annotations

from cbc.modules.ops.infrastructure.collections import settings_collection


async def autopilot_default() -> bool:
    """The admin's default for bids created without an explicit choice."""
    stored = await settings_collection().find_one({"_id": "pipeline"}) or {}
    return bool(stored.get("autopilotDefault", False))


# Until the code ladder has been checked against the estimators' own quotes, a
# bid prices the way it did unless an admin switches it in Settings > Pipeline.
DEFAULT_PRICING_ENGINE = "legacy"
PRICING_ENGINES = ("legacy", "v2")


def engine_from(stored: dict) -> str:
    engine = stored.get("pricingEngine")
    return engine if engine in PRICING_ENGINES else DEFAULT_PRICING_ENGINE


async def pricing_engine() -> str:
    """`v2` prices in code (quoting's ladder); `legacy` runs the Claude pricing pass."""
    return engine_from(await settings_collection().find_one({"_id": "pipeline"}) or {})
