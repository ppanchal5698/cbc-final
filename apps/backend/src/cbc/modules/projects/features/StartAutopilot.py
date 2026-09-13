"""POST /api/projects/{code}/orchestrate/autopilot - start the extract -> price -> propose chain.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api.jobs import PipelineJobActive
from cbc.modules.projects.api import autopilot as orchestrator
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/orchestrate", tags=["orchestrate"])


@router.post("/autopilot", status_code=201)
async def start_autopilot(code: str, actor: Actor) -> dict:
    """Enqueue extract_bid_set with orchestrate=true (domain chain)."""
    project = await load(code)
    try:
        job = await orchestrator.enqueue_autopilot(project["_id"], actor=actor)
    except PipelineJobActive as exc:
        raise HTTPException(
            409,
            detail={
                "message": "A Claude run is already in progress for this bid",
                "activeJob": serialise(exc.active),
            },
        ) from exc
    return {"job": serialise(job), "chain": list(orchestrator.ORCHESTRATED_CHAIN)}
