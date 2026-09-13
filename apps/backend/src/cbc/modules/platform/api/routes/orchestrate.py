"""Autopilot orchestration — chains domain jobs instead of run_full_pipeline."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.shared.mongo import serialise
from cbc.shared.auth import Actor
from cbc.http.projects_access import load
from cbc.services import orchestrator
from cbc.services.jobs import PipelineJobActive

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
