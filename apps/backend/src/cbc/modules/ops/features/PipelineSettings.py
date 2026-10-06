"""GET and PUT /api/settings/pipeline - whether a new bid starts on autopilot, and how it is read and priced."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cbc.modules.ops.api import audit, pipeline
from cbc.modules.ops.infrastructure.collections import settings_collection
from cbc.shared.auth import Actor, require_admin

# Every settings route is admin-only: they read or write provider credentials,
# spawn CLI processes, or change how every bid behaves.
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineSettings(BaseModel):
    """How a new bid behaves when a drawing lands on it."""

    autopilotDefault: bool = False
    # Which pricing runs a bid's match-and-price job: the code ladder, or the
    # Claude pass it replaces. Kept switchable until v2 is checked against the
    # estimators' own quotes. Omitted, it is left as it is: a screen that saves
    # only the autopilot default must not reset the engine.
    pricingEngine: Literal["legacy", "v2"] | None = None
    # The same for the extract job: the take-off in code, with the model asked only
    # what the parsers cannot read, or the Claude extraction wave.
    extractionEngine: Literal["legacy", "v2"] | None = None
    # And the build_proposal job: the proposal in code, or the Claude pass.
    proposalEngine: Literal["legacy", "v2"] | None = None


@router.get("/pipeline")
async def get_pipeline_settings() -> dict[str, Any]:
    stored = await settings_collection().find_one({"_id": "pipeline"}) or {}
    return {
        "autopilotDefault": bool(stored.get("autopilotDefault", False)),
        "pricingEngine": pipeline.engine_from(stored),
        "extractionEngine": pipeline.engine_from(stored, "extraction"),
        "proposalEngine": pipeline.engine_from(stored, "proposal"),
        "note": (
            "Autopilot runs Phase 0-6 in one pass when a drawing is uploaded. The "
            "openings are priced before anyone checks them and everything uncertain "
            "is flagged for review at the end. Nothing is ever sent (NFR-1). Each "
            "bid can override this."
        ),
        "updatedAt": stored.get("updatedAt"),
        "updatedBy": stored.get("updatedBy"),
    }


@router.put("/pipeline")
async def save_pipeline_settings(body: PipelineSettings, actor: Actor) -> dict[str, Any]:
    await settings_collection().update_one(
        {"_id": "pipeline"},
        {"$set": {"autopilotDefault": body.autopilotDefault,
                  **({"pricingEngine": body.pricingEngine} if body.pricingEngine else {}),
                  **({"extractionEngine": body.extractionEngine} if body.extractionEngine else {}),
                  **({"proposalEngine": body.proposalEngine} if body.proposalEngine else {}),
                  "updatedAt": _now(), "updatedBy": actor}},
        upsert=True,
    )
    await audit.record(
        "settings.pipeline.update", actor, {},
        after=body.model_dump(exclude_none=True),
    )
    return await get_pipeline_settings()
