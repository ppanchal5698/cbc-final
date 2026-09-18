"""POST /api/learning/apply - fold the corrections recorded so far into the matcher (FR-13).

The drain also runs after every pass. This is for an operator who has just fixed
a batch of matches and wants the next bid to know now.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.api import feedback

router = APIRouter(prefix="/api/learning", tags=["operational"])


@router.post("/apply")
async def apply_learning() -> dict[str, Any]:
    return await feedback.apply_to_learning()
