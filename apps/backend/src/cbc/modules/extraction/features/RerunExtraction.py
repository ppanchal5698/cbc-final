"""POST /api/projects/{code}/line-items/rerun - read the drawings again, keeping the estimator's decisions.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.extraction.api import line_items
from cbc.modules.ops.api.jobs import enqueue_pipeline
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


@router.post("/rerun")
async def rerun_extraction(code: str, actor: Actor) -> dict:
    """Ask Claude to read the drawings again.

    Confirmed lines and hand-added lines are written down to disk first, so the
    re-run reconciles against the estimator's decisions instead of overwriting them.
    """
    project = await load(code)
    await line_items.export_line_items(project)
    job = await enqueue_pipeline("rerun_extraction", project["_id"], actor=actor)
    return {"job": serialise(job)}
