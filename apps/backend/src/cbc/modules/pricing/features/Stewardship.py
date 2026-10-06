"""/stewardship under /api/reference - who keeps each data set current, and what is due (NFR-10).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.pricing.api import stewardship
from cbc.modules.pricing.infrastructure.reference_io import run_sync
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/stewardship")
async def get_stewardship(actor: Actor) -> dict[str, Any]:
    return {
        "sets": serialise(await run_sync(stewardship.overview)),
        "note": "Owners and cadences are the requirements' proposal (6.3) for CBC to confirm. "
                "A set past its review is due, not refused: pricing still reads it.",
    }
