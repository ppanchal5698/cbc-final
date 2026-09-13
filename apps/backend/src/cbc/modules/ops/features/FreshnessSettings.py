"""GET and PUT /api/settings/freshness - how long a price book or last-PO cost stays trusted."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from cbc.domain import freshness as freshness_core
from cbc.modules.ops.api import audit
from cbc.modules.ops.api import freshness as freshness_settings
from cbc.modules.ops.infrastructure.collections import settings_collection
from cbc.shared.auth import Actor, require_admin

# Every settings route is admin-only: they read or write provider credentials,
# spawn CLI processes, or change how every bid behaves.
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FreshnessSettings(BaseModel):
    """How long a price book or last-PO cost stays inside the review window."""

    catalogStaleMonths: int = Field(ge=1, le=freshness_core.MAX_MONTHS)
    discardAfterMonths: int = Field(ge=1, le=freshness_core.MAX_MONTHS)

    @model_validator(mode="after")
    def discard_after_the_review_window(self) -> FreshnessSettings:
        if self.catalogStaleMonths >= self.discardAfterMonths:
            raise ValueError(
                "discardAfterMonths must be greater than catalogStaleMonths"
            )
        return self


@router.get("/freshness")
async def get_freshness_settings() -> dict[str, Any]:
    freshness_settings.clear_cache()
    return freshness_settings.as_payload(await freshness_settings.load())


@router.put("/freshness")
async def save_freshness_settings(body: FreshnessSettings, actor: Actor) -> dict[str, Any]:
    document = {
        "catalogStaleMonths": body.catalogStaleMonths,
        "discardAfterMonths": body.discardAfterMonths,
        "catalogStaleDays": freshness_core.days_from_months(body.catalogStaleMonths),
        "discardAfterDays": freshness_core.days_from_months(body.discardAfterMonths),
        "updatedAt": _now(),
        "updatedBy": actor,
    }
    await settings_collection().update_one(
        {"_id": freshness_settings.DOC_ID},
        {"$set": document},
        upsert=True,
    )
    freshness_settings.clear_cache()
    await audit.record(
        "settings.freshness.update",
        actor,
        {},
        after={
            "catalogStaleMonths": body.catalogStaleMonths,
            "discardAfterMonths": body.discardAfterMonths,
        },
    )
    return await get_freshness_settings()
