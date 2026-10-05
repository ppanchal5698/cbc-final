"""The memory_learn job: the curator records a bid once an estimator approves it."""
from __future__ import annotations

import logging
from typing import Any

from cbc.modules.memory.api import curator
from cbc.modules.memory.infrastructure import graph
from cbc.modules.ops.api import jobs
from cbc.shared.mongo import oid

log = logging.getLogger("cbc.memory")


async def on_proposal_approved(project_id: Any, approved_by: Any = None, **_: Any) -> None:
    """Heard from quoting. Queues the learning; never fails the sign-off it follows."""
    if not graph.configured():
        return
    try:
        await jobs.enqueue("memory_learn", payload={"projectId": str(project_id)}, actor="memory-curator")
    except Exception:
        log.exception("could not queue memory_learn for %s", project_id)


async def run(job: dict[str, Any]) -> str:
    project_id = oid((job.get("payload") or {}).get("projectId"))
    learned = await curator.learn_bid(project_id)
    return "bid learned" if learned else "nothing to learn: no approved proposal on this bid"
