"""PATCH /api/projects/{code}/quote/settings - tax jurisdiction and freight; reprices.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.quotes import QuoteSettings
from cbc.modules.quoting.infrastructure.collections import quotes
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("/settings")
async def update_settings(code: str, body: QuoteSettings, actor: Actor) -> dict:
    project = await load(code)
    changes = body.model_dump(exclude_unset=True)
    await quotes().update_one(
        {"projectId": project["_id"]},
        {"$set": {**changes, "updatedAt": _now()}, "$setOnInsert": {"createdAt": _now()}},
        upsert=True,
    )
    await audit.record("quote.settings", actor, {"projectId": project["_id"]}, after=changes)
    return {"totals": await quote_service.persist(project)}
