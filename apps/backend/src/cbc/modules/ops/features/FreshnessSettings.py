"""GET and PUT /api/settings/freshness - how long a price book or last-PO cost stays trusted."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import freshness_rules as freshness_core
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
    """A price sheet's review window (Matrix 6.3), and a P21 cost's fresh and discard bands (6.2).

    `.claude/rules/data-stewardship.md`: moving one must not move the other. The
    review window used to have to end before the discard band, tying a price-sheet
    rule to a purchase-order one; now only the two cost bands are ordered. The
    Settings screen sends no `freshMonths`, and the stored band then stands.
    """

    catalogStaleMonths: int = Field(ge=1, le=freshness_core.MAX_MONTHS)
    discardAfterMonths: int = Field(ge=1, le=freshness_core.MAX_MONTHS)
    freshMonths: int | None = Field(default=None, ge=1, le=freshness_core.MAX_MONTHS)


@router.get("/freshness")
async def get_freshness_settings() -> dict[str, Any]:
    freshness_settings.clear_cache()
    return freshness_settings.as_payload(await freshness_settings.load())


@router.put("/freshness")
async def save_freshness_settings(body: FreshnessSettings, actor: Actor) -> dict[str, Any]:
    freshness_settings.clear_cache()
    fresh_months = body.freshMonths or (await freshness_settings.load()).fresh_months
    if fresh_months >= body.discardAfterMonths:
        raise HTTPException(422, "discardAfterMonths must be greater than freshMonths")
    document = {
        "catalogStaleMonths": body.catalogStaleMonths,
        "discardAfterMonths": body.discardAfterMonths,
        "freshMonths": fresh_months,
        "catalogStaleDays": freshness_core.days_from_months(body.catalogStaleMonths),
        "discardAfterDays": freshness_core.days_from_months(body.discardAfterMonths),
        "freshDays": freshness_core.days_from_months(fresh_months),
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
            "freshMonths": fresh_months,
        },
    )
    return await get_freshness_settings()
