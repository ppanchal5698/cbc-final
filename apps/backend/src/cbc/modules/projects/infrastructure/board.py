"""The counts the board and the stage bar render beside each bid.

Openings, documents and quotes come from extraction, intake and quoting through
bound sources, jobs through ops.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.ops.api import identity as ops_identity
from cbc.modules.ops.api import jobs as ops_jobs
from cbc.modules.projects.api import board_sources
from cbc.modules.projects.infrastructure.collections import calls as calls_collection
from cbc.shared.mongo import serialise


async def _count_by_project(collection, ids: list[Any]) -> dict[Any, int]:
    rows = await collection.aggregate(
        [{"$match": {"projectId": {"$in": ids}}},
         {"$group": {"_id": "$projectId", "n": {"$sum": 1}}}]
    ).to_list(length=len(ids) + 1)
    return {row["_id"]: row["n"] for row in rows}


async def decorate_many(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the counts the board and stage bar render, for a whole page of bids.

    Five aggregations for the entire list, not six queries per bid. The board is
    the landing page and its cost used to grow linearly with the number of open
    bids - at the default limit that was three hundred sequential round trips.
    """
    if not projects:
        return []
    ids = [project["_id"] for project in projects]

    # Statuses and confirmations in one pass: `status` carries provenance
    # (`by_hand`) in the same field as review state, so a confirmed hand-added
    # line is not in the `clear` bucket. Confirmation is what "cleared" means to
    # an estimator, so count the thing that records it.
    counts, confirmed = await board_sources.opening_counts(ids)

    quotes = await board_sources.quotes(ids)
    active = await ops_jobs.active_by_project(ids)

    documents = await board_sources.document_counts(ids)
    calls = await _count_by_project(calls_collection(), ids)

    # One lookup for the page, so the board can print who a bid is assigned to
    # rather than an email address.
    people = await ops_identity.directory(
        [project.get("assignedEstimator") or "" for project in projects]
    )

    decorated = []
    for project in projects:
        project_id = project["_id"]
        by_status = counts.get(project_id, {})
        assigned = (project.get("assignedEstimator") or "").lower()
        decorated.append(
            {
                **serialise(project),
                # Absent on every bid opened before the board gained these
                # fields, so default here rather than backfilling the
                # collection: a bid with no recorded outcome is simply open.
                "bidStatus": project.get("bidStatus") or "bid",
                "outcome": project.get("outcome") or "",
                "assignedEstimator": assigned,
                "estimator": people.get(assigned),
                "counts": {
                    "total": sum(by_status.values()),
                    "clear": confirmed.get(project_id, 0),
                    "needsLook": by_status.get("needs_look", 0),
                    "duplicate": by_status.get("duplicate", 0),
                    "byHand": by_status.get("by_hand", 0),
                },
                "documentCount": documents.get(project_id, 0),
                "version": project.get("version", 1),
                "callCount": calls.get(project_id, 0),
                "quoteTotal": quotes.get(project_id, {}).get("grandTotal"),
                "activeJob": serialise(active[project_id]) if project_id in active else None,
            }
        )
    return decorated


async def decorate(project: dict[str, Any]) -> dict[str, Any]:
    """One bid, through the same code path as the board - no second implementation."""
    return (await decorate_many([project]))[0]
