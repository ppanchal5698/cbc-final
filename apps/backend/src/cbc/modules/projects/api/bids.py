"""What other modules may record on a bid, and what a bid announces."""
from __future__ import annotations

from typing import Any

from cbc.modules.projects.infrastructure.collections import bid_requests

# Published with project_id= while a bid is being deleted - after its jobs are
# cancelled, before its record goes - so each module removes its own rows.
PROJECT_DELETED = "projects.project_deleted"


async def set_version(project_id: Any, number: int) -> None:
    """The bid's current version, after an addendum snapshot."""
    await bid_requests().update_one({"_id": project_id}, {"$set": {"version": number}})
