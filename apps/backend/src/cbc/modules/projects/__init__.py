"""projects: the bid record everything else hangs off.

Opening, listing, changing and deleting a bid; seeding one from a prior quote; the
calls, notes and RFIs logged against it; starting autopilot. It owns
`bidRequests`, `calls` and `counters`.

Other modules import only `cbc.modules.projects.api`. Slices are imported inside
`register`, so a module that only wants the lookup does not load every handler.
"""
from __future__ import annotations


def subscribe() -> None:
    """What projects listens for. `register` calls it; the worker, which mounts no routes, calls it itself."""
    from cbc.modules.ops.api import jobs as ops_jobs
    from cbc.modules.projects.api import saga
    from cbc.shared import events

    events.subscribe(ops_jobs.JOB_REQUEUED, saga.on_job_requeued)
    events.subscribe(events.QUOTE_COMPLETED, saga.on_quote_completed)


def register(app) -> None:
    """Mount this module's routes, and subscribe to what it listens for."""
    subscribe()

    from cbc.modules.projects.features import (
        CreateProject,
        DeleteCall,
        DeleteProject,
        GetProject,
        ListCalls,
        ListPriorQuotes,
        ListProjects,
        LogCall,
        ResolveRfi,
        ReusePriorQuote,
        StartAutopilot,
        UpdateProject,
    )

    for feature in (
        ListProjects,
        CreateProject,
        ListPriorQuotes,
        ReusePriorQuote,
        GetProject,
        UpdateProject,
        DeleteProject,
        ListCalls,
        LogCall,
        ResolveRfi,
        DeleteCall,
        StartAutopilot,
    ):
        app.include_router(feature.router)


async def ensure_indexes() -> None:
    from cbc.modules.projects.infrastructure.collections import ensure_indexes as build

    await build()
