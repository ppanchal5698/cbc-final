"""GET /api/projects/{code}/review-flags - what the estimator must look at before a quote goes out.

NFR-2: review flags are visible from day one. They are derived on every read, so a
flag matches the openings and priced lines as they are now rather than as they were
when the last pass ran, merged with the flags the quality-reviewer pass wrote.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.api.validation import review
from cbc.modules.projects.api.lookup import load

router = APIRouter(prefix="/api/projects/{code}/review-flags", tags=["review"])


@router.get("")
async def list_review_flags(code: str) -> dict[str, Any]:
    project = await load(code)
    # Derivation reads the tier sheet synchronously (excluded vendors).
    flags = await asyncio.to_thread(review.read_flags, project["slug"])
    return {"flags": flags}
