"""A bid's proposal approval - the estimator's sign-off (FR-9) - for modules that learn from it.

An approved proposal is the one signal in the system that a bid came out right:
a named estimator read every line and put their name to it. The memory graph
learns from exactly these bids and nothing else.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.quoting.infrastructure.collections import proposals

# Published by MarkComplete once the approval is stored. Payload: project_id, approved_by.
PROPOSAL_APPROVED = "quoting.proposal_approved"


async def approval_for(project_id: Any) -> dict[str, Any] | None:
    """The bid's approved proposal, or None while nobody has signed it off."""
    return await proposals().find_one({"projectId": project_id, "approvedBy": {"$nin": [None, ""]}})


async def approved_project_ids() -> list[Any]:
    """Every bid with an approved proposal."""
    return await proposals().distinct("projectId", {"approvedBy": {"$nin": [None, ""]}})
