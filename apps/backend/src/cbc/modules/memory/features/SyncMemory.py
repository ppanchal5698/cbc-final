"""The memory_sync job, and POST /api/memory/sync to ask for one now."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from cbc.modules.memory.api import curator
from cbc.modules.memory.features import ReviewMemory
from cbc.modules.memory.infrastructure import graph
from cbc.modules.ops.api import jobs
from cbc.shared.auth import AdminActor, require_admin

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_admin)])


async def enqueue_sync(actor: str = "memory-curator", delay_seconds: int = 0) -> dict[str, Any]:
    """Queue a sync. Coalesced: a sync already queued or running is returned instead."""
    return await jobs.enqueue("memory_sync", payload={"scope": "all"}, actor=actor, delay_seconds=delay_seconds)


# How often the API asks whether a sync is due. Short, so a graph that was down at
# start-up is filled minutes after it comes back, not one interval later.
CHECK_SECONDS = 300


async def sync_due() -> bool:
    """Never synced, or the last sync is older than the interval."""
    rows = await graph.read("MATCH (m:Meta {key: 'sync'}) RETURN m.lastSyncAt AS at")
    if not rows or not rows[0].get("at"):
        return True
    last = datetime.fromisoformat(rows[0]["at"])
    return (datetime.now(timezone.utc) - last).total_seconds() >= curator.SYNC_INTERVAL_SECONDS


async def sync_on_timer() -> None:
    """The periodic check the API runs. Queues a sync only when the graph is up and
    one is due, so a Neo4j outage costs a few skipped checks, not a dead job."""
    if graph.configured() and await graph.reachable() and await sync_due():
        await enqueue_sync()


async def run(job: dict[str, Any]) -> str:
    counts = await curator.sync_all()
    await ReviewMemory.enqueue_review()
    return "synced " + ", ".join(f"{k} {v}" for k, v in counts.items())


@router.post("/sync")
async def sync_now(actor: AdminActor) -> dict[str, Any]:
    if not graph.configured():
        raise HTTPException(409, "the memory graph is not configured (NEO4J_URI is empty)")
    job = await enqueue_sync(actor=actor)
    return {"jobId": str(job["_id"]), "status": job.get("status")}
