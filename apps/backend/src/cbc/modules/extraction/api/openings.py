"""A bid's openings, for the modules and the runner that read or stamp them.
"""
from __future__ import annotations

from typing import Any, TypedDict

from cbc.modules.extraction.infrastructure.collections import failed_extractions, openings

# An estimator confirmed openings on a bid: project_id, count.
LINES_CONFIRMED = "extraction.lines_confirmed"


class OpeningRef(TypedDict, total=False):
    """A stored opening, as other modules read it.

    Still the stored document at runtime: a TypedDict converts nothing.
    """

    _id: Any
    projectId: Any
    mark: str
    doorNumber: str
    handing: str
    finish: str
    fireRating: str
    fire_rating: str
    status: str
    alternateGroup: str


async def list_for_project(
    project_id: Any, *, sort: list[tuple[str, int]] | None = None, limit: int | None = None
) -> list[OpeningRef]:
    cursor = openings().find({"projectId": project_id})
    if sort is not None:
        cursor = cursor.sort(sort)
    return await cursor.to_list(limit)


async def count(project_id: Any, *, status: str) -> int:
    return await openings().count_documents({"projectId": project_id, "status": status})


async def reopen_confirmed(project_id: Any) -> None:
    """An extraction that needs review puts every confirmed opening back in front of the estimator."""
    await openings().update_many(
        {"projectId": project_id, "status": "clear"},
        {"$set": {"status": "needs_look"}},
    )


async def set_version(project_id: Any, version_id: Any) -> None:
    """Live openings belong to this version (estimateVersionId), after a snapshot."""
    await openings().update_many({"projectId": project_id}, {"$set": {"estimateVersionId": version_id}})


async def update_fields(opening_id: Any, fields: dict[str, Any]) -> None:
    await openings().update_one({"_id": opening_id}, {"$set": fields})


async def apply_bulk(requests: list[Any]) -> None:
    """A sync's upserts and updates, unordered so one bad row does not stop the rest."""
    await openings().bulk_write(requests, ordered=False)


async def record_failed(documents: list[dict[str, Any]]) -> None:
    """Keep payloads that failed the schema gate, for operators."""
    await failed_extractions().insert_many(documents)


async def counts_by_project(ids: list[Any]) -> tuple[dict[Any, dict[str, int]], dict[Any, int]]:
    """Per bid: openings by status, and how many are confirmed.

    `status` carries provenance (`by_hand`) in the same field as review state, so a
    confirmed hand-added line is not in the `clear` bucket. Confirmation is what
    "cleared" means to an estimator, so it is counted from what records it.
    """
    status_rows = await openings().aggregate(
        [
            {"$match": {"projectId": {"$in": ids}}},
            {
                "$group": {
                    "_id": {"projectId": "$projectId", "status": "$status"},
                    "n": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=None)

    confirmed_rows = await openings().aggregate(
        [
            {
                "$match": {
                    "projectId": {"$in": ids},
                    "confirmedAt": {"$exists": True, "$ne": None},
                }
            },
            {"$group": {"_id": "$projectId", "n": {"$sum": 1}}},
        ]
    ).to_list(length=None)

    counts: dict[Any, dict[str, int]] = {}
    confirmed = {row["_id"]: row["n"] for row in confirmed_rows}
    for row in status_rows:
        project_id, status = row["_id"]["projectId"], row["_id"]["status"]
        counts.setdefault(project_id, {})[status] = row["n"]
    return counts, confirmed


async def distinct_groups(project_id: Any) -> list[Any]:
    """Every alternate group an opening on this bid is assigned to."""
    return await openings().distinct("alternateGroup", {"projectId": project_id})


async def count_in_group(project_id: Any, group: str | None) -> int:
    return await openings().count_documents({"projectId": project_id, "alternateGroup": group})


async def assign_group(project_id: Any, ids: list[Any], group: str | None, *, at: Any) -> int:
    """Move these openings into a group; returns how many actually moved."""
    result = await openings().update_many(
        {"_id": {"$in": ids}, "projectId": project_id, "alternateGroup": {"$ne": group}},
        {"$set": {"alternateGroup": group, "updatedAt": at}},
    )
    return result.modified_count
