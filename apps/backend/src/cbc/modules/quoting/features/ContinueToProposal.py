"""POST /api/projects/{code}/quote/continue-to-proposal - write the approved quote down, queue the proposal.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.ops.api import audit
from cbc.modules.ops.api.jobs import enqueue_pipeline
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import priced_lines
from cbc.modules.quoting.api import quote as quote_service
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


@router.post("/continue-to-proposal")
async def continue_to_proposal(code: str, actor: Actor) -> dict:
    """Phase boundary: write the approved quote down, then enqueue the proposal build."""
    project = await load(code)
    await quote_service.persist(project)
    await priced_lines.export_quote_lines(project)

    job = await enqueue_pipeline("build_proposal", project["_id"], actor=actor)
    await audit.record("project.continue_to_proposal", actor, {"projectId": project["_id"]})
    return {"job": serialise(job)}
