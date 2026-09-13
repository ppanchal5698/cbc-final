"""POST /api/projects/{code}/line-items/continue-to-quote - hand confirmed openings to pricing.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.ops.api.jobs import enqueue_pipeline
from cbc.modules.projects.api.lookup import load
from cbc.services import sync  # ponytail: legacy kernel; the export moves with the extraction job (Phase 4)
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


@router.post("/continue-to-quote")
async def continue_to_quote(code: str, actor: Actor) -> dict:
    """Phase boundary: push confirmed openings down to disk and enqueue pricing."""
    project = await load(code)

    outstanding = await openings().count_documents(
        {"projectId": project["_id"], "status": "needs_look"}
    )
    await sync.export_line_items(project)

    job = await enqueue_pipeline("match_and_price", project["_id"], actor=actor)
    await audit.record(
        "project.continue_to_quote",
        actor,
        {"projectId": project["_id"]},
        note=f"{outstanding} item(s) still flagged at hand-off",
    )
    return {"job": serialise(job), "stillFlagged": outstanding}
