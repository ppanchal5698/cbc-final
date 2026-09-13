"""What other modules may record on a bid, and what a bid announces."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.projects.infrastructure.collections import bid_requests

# Published with project_id= while a bid is being deleted - after its jobs are
# cancelled, before its record goes - so each module removes its own rows.
PROJECT_DELETED = "projects.project_deleted"


async def set_version(project_id: Any, number: int) -> None:
    """The bid's current version, after an addendum snapshot."""
    await bid_requests().update_one({"_id": project_id}, {"$set": {"version": number}})


async def add_alternate(project_id: Any, name: str) -> None:
    """Name a new alternate group on the bid."""
    await bid_requests().update_one(
        {"_id": project_id},
        {"$addToSet": {"alternates": name}, "$set": {"updatedAt": datetime.now(timezone.utc)}},
    )


async def record_hand_off(project_id: Any, recipient: str | None) -> None:
    """The estimator signed the proposal off and routed it to `recipient`."""
    now = datetime.now(timezone.utc)
    await bid_requests().update_one(
        {"_id": project_id},
        {"$set": {"handedOffTo": recipient, "handedOffAt": now, "updatedAt": now}},
    )
