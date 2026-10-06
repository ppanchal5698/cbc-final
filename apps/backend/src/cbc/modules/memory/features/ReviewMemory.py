"""The memory_review job - the steward, then the historian - queued after every sync
and every learned bid; POST /api/memory/findings/dismiss for an admin's call that a
finding is not a problem."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.memory.api import curator, historian, steward
from cbc.modules.memory.infrastructure import graph
from cbc.modules.ops.api import jobs
from cbc.shared.auth import AdminActor, require_admin

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_admin)])


async def enqueue_review(actor: str = "memory-curator") -> dict[str, Any]:
    """Queue the agents. Coalesced: a review already queued or running is returned instead."""
    return await jobs.enqueue("memory_review", payload={"scope": "all"}, actor=actor)


async def run(job: dict[str, Any]) -> str:
    if not await graph.reachable():
        raise curator.GraphUnavailable("the memory graph is not reachable")
    found = await steward.review()
    learned = await historian.reflect()
    return (f"{found['open']} open finding(s), {found['resolved']} resolved, {found['explained']} explained; "
            f"{learned['insights']} customer insight(s) written")


class Dismissal(BaseModel):
    key: str = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


@router.post("/findings/dismiss")
async def dismiss(body: Dismissal, actor: AdminActor) -> dict[str, Any]:
    if not graph.configured():
        raise HTTPException(409, "the memory graph is not configured (NEO4J_URI is empty)")
    if not await steward.dismiss(body.key, by=actor, note=body.note):
        raise HTTPException(404, "no such finding")
    return {"key": body.key, "status": "dismissed"}
