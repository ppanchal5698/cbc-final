"""memory: the Neo4j memory graph and the curator that keeps it.

DocumentDB stays the system of record. The graph is its connected copy -
vendors, multipliers, customers, catalog items, reference data - plus what every
approved bid taught: who it was for, what each line was priced as, and the
workflow that produced it. It owns no DocumentDB collection.

Optional by design: with NEO4J_URI empty or Neo4j down, nothing else changes.
Other modules import only `cbc.modules.memory.api`.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount the routes and hear approvals (the API runs MarkComplete)."""
    from cbc.modules.memory.features import LearnFromBid, MemorySummary, SyncMemory
    from cbc.modules.quoting.api import approvals
    from cbc.shared import events

    for router in (MemorySummary.admin, MemorySummary.router, SyncMemory.router):
        app.include_router(router)
    events.subscribe(approvals.PROPOSAL_APPROVED, LearnFromBid.on_proposal_approved)


def register_jobs() -> None:
    """Plug the curator's jobs into ops' worker."""
    from functools import partial

    from cbc.modules.memory.features import LearnFromBid, SyncMemory
    from cbc.modules.ops.api import worker

    # Neo4j being down is transient, so no failure here is permanent: the job retries.
    worker.register("memory_sync", partial(worker.run_locally, work=SyncMemory.run, permanent=()))
    worker.register("memory_learn", partial(worker.run_locally, work=LearnFromBid.run, permanent=()))


def background_jobs():
    """Periodic work while the API runs: (async callable, seconds)."""
    from cbc.modules.memory.features.SyncMemory import CHECK_SECONDS, sync_on_timer

    return [(sync_on_timer, CHECK_SECONDS)]
