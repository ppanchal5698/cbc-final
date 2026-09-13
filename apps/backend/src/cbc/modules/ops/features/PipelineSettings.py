"""GET and PUT /api/settings/pipeline - whether a new bid starts on autopilot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cbc.modules.ops.api import audit
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


@router.get("/pipeline")
async def get_pipeline_settings() -> dict[str, Any]:
    stored = await settings_collection().find_one({"_id": "pipeline"}) or {}
    return {
        "autopilotDefault": bool(stored.get("autopilotDefault", False)),
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
                  "updatedAt": _now(), "updatedBy": actor}},
        upsert=True,
    )
    await audit.record(
        "settings.pipeline.update", actor, {},
        after={"autopilotDefault": body.autopilotDefault},
    )
    return await get_pipeline_settings()
