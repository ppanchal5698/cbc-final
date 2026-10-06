"""The pipeline policy other modules read: whether a new bid starts on autopilot,
and which engine reads it, prices it and builds its proposal."""
from __future__ import annotations

from cbc.modules.ops.infrastructure.collections import settings_collection


async def autopilot_default() -> bool:
    """The admin's default for bids created without an explicit choice."""
    stored = await settings_collection().find_one({"_id": "pipeline"}) or {}
    return bool(stored.get("autopilotDefault", False))


# Until each phase in code has been checked against the estimators' own work, a
# bid is read and priced the way it was unless an admin switches it in
# Settings > Pipeline - each phase on its own switch.
DEFAULT_ENGINE = "legacy"
ENGINES = ("legacy", "v2")


def engine_from(stored: dict, phase: str = "pricing") -> str:
    engine = stored.get(f"{phase}Engine")
    return engine if engine in ENGINES else DEFAULT_ENGINE


async def pricing_engine() -> str:
    """`v2` prices in code (quoting's ladder); `legacy` runs the Claude pricing pass."""
    return engine_from(await settings_collection().find_one({"_id": "pipeline"}) or {})


async def extraction_engine() -> str:
    """`v2` reads a bid set in code, asking the model only what the parsers cannot
    read; `legacy` runs the Claude extraction wave."""
    return engine_from(await settings_collection().find_one({"_id": "pipeline"}) or {}, "extraction")


async def proposal_engine() -> str:
    """`v2` builds the proposal in code - the document the screen shows, filed with
    its review sheet, email draft and PDF; `legacy` runs the Claude proposal pass."""
    return engine_from(await settings_collection().find_one({"_id": "pipeline"}) or {}, "proposal")
