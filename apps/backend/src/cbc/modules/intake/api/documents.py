"""A bid's documents, for the runner that reads them and the board that counts them."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from cbc.modules.intake.infrastructure.collections import documents


async def mark_received(project_id: Any, state: str, *, uploaded_by: datetime | None) -> int:
    """Move this bid's still-`received` documents - uploaded no later than `uploaded_by`,
    when given - to `state`. Later uploads are left for the next pass."""
    query: dict[str, Any] = {"projectId": project_id, "state": "received"}
    if uploaded_by is not None:
        query["uploadedAt"] = {"$lte": uploaded_by}
    result = await documents().update_many(query, {"$set": {"state": state}})
    return int(result.modified_count)


async def mark_all_read(project_id: Any) -> None:
    await documents().update_many({"projectId": project_id}, {"$set": {"state": "read"}})


async def count_received_after(project_id: Any, uploaded_after: datetime | None) -> int:
    """Documents still `received` that landed after `uploaded_after` - a pass's stragglers."""
    query: dict[str, Any] = {"projectId": project_id, "state": "received"}
    if uploaded_after is not None:
        query["uploadedAt"] = {"$gt": uploaded_after}
    return await documents().count_documents(query)


async def count_by_project(ids: list[Any]) -> dict[Any, int]:
    rows = await documents().aggregate(
        [{"$match": {"projectId": {"$in": ids}}},
         {"$group": {"_id": "$projectId", "n": {"$sum": 1}}}]
    ).to_list(length=len(ids) + 1)
    return {row["_id"]: row["n"] for row in rows}
