"""FR-11: seed a draft estimate from the closest prior quote.

Match on brand / architect / GC. Records `templateSourceEstimateId` on the new
bid so the reuse is attributable, not silent. The lines themselves are quoting's:
it hears `TEMPLATE_CHOSEN` and carries them across.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.projects.infrastructure.collections import bid_requests


async def find_prior(
    *,
    brand: str | None = None,
    architect: str | None = None,
    gc: str | None = None,
    exclude_id: Any = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Closest prior bidRequests, scored by how many of the three keys match."""
    clauses: list[dict[str, Any]] = []
    if brand:
        clauses.append({"brand": brand})
    if architect:
        clauses.append({"architect": architect})
    if gc:
        clauses.append({"gc": gc})
    if not clauses:
        return []

    query: dict[str, Any] = {"$or": clauses}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}

    candidates = await bid_requests().find(query).sort("updatedAt", -1).to_list(50)
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in candidates:
        score = 0
        if brand and row.get("brand") == brand:
            score += 3
        if architect and row.get("architect") == architect:
            score += 2
        if gc and row.get("gc") == gc:
            score += 2
        if score:
            scored.append((score, row))
    # Stable, so equal scores keep the newest-first order of the query: a tie
    # broken by `updatedAt` ascending made the oldest matching job the template.
    scored.sort(key=lambda pair: -pair[0])
    return [row for _, row in scored[:limit]]


async def seed_from_prior(project: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Mark the new bid as templated from `prior` and copy mode metadata."""
    from cbc.modules.projects.api import bids
    from cbc.shared import events

    await events.publish(bids.TEMPLATE_CHOSEN, project=project, prior=prior)
    await bid_requests().update_one(
        {"_id": project["_id"]},
        {
            "$set": {
                "mode": "templated",
                "sourceType": "templated",
                "templateSourceEstimateId": prior["_id"],
                "templateSourceCode": prior.get("code"),
            }
        },
    )
    return {
        "templateSourceEstimateId": prior["_id"],
        "templateSourceCode": prior.get("code"),
        "brand": prior.get("brand"),
        "architect": prior.get("architect"),
        "gc": prior.get("gc"),
    }
