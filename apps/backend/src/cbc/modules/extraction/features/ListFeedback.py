"""GET /api/projects/{code}/feedback-events - the corrections recorded on a bid, newest first (FR-13).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.infrastructure.collections import feedback_events
from cbc.modules.projects.api.lookup import load
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


@router.get("/feedback-events")
async def list_feedback(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await feedback_events().find({"bidRequestId": project["_id"]}).sort(
        "occurredAt", -1
    ).to_list(500)
    return {"feedbackEvents": serialise(rows)}
