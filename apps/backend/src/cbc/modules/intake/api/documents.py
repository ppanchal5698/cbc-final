"""A bid's documents, for the pass that reads them and the board that counts them."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from cbc.modules.intake.infrastructure.collections import documents

# parse.state values that mean MinerU is not finished yet — Claude must wait.
_PARSE_INCOMPLETE = frozenset({"queued", "running"})


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


async def incomplete_parses(project_id: Any) -> list[dict[str, Any]]:
    """Documents on this bid whose MinerU parse is still queued or running.

    Used by the extract worker so Claude does not start until GPU parsing finishes
    when PARSER_URL is set. Failed / missing parse fields are not incomplete —
    those fall back to pdf-tools.
    """
    return await documents().find(
        {"projectId": project_id, "parse.state": {"$in": list(_PARSE_INCOMPLETE)}},
        {"filename": 1, "parse.state": 1},
    ).to_list(length=200)


async def count_by_project(ids: list[Any]) -> dict[Any, int]:
    rows = await documents().aggregate(
        [{"$match": {"projectId": {"$in": ids}}},
         {"$group": {"_id": "$projectId", "n": {"$sum": 1}}}]
    ).to_list(length=len(ids) + 1)
    return {row["_id"]: row["n"] for row in rows}


async def mineru_signals_by_path(project_id: Any, slug: str) -> dict[str, dict[int, dict[str, Any]]]:
    """Per raw-PDF path, per page: whether MinerU verified it and how many blocks it read.

    Extraction routes pages to a vision read from this, and used to reach into
    `intake.infrastructure.collections` to get it - past intake's api, which the
    layering rule forbids. The question is about intake's documents, so intake
    answers it.

    Best effort by design: a bid with no parse yet is the normal case, and the
    caller falls back to pdf-tools.
    """
    from cbc.modules.intake.infrastructure.collections import document_pages, documents

    if not project_id or not slug:
        return {}
    try:
        docs = await documents().find({"projectId": project_id}, {"filename": 1}).to_list(500)
        id_to_name = {
            row["_id"]: row.get("filename")
            for row in docs
            if isinstance(row, dict) and row.get("_id") is not None
        }
        found: dict[str, dict[int, dict[str, Any]]] = {}
        cursor = document_pages().find(
            {"projectId": project_id},
            {"documentId": 1, "page": 1, "verified": 1, "blocks": 1},
        )
        async for row in cursor:
            if not isinstance(row, dict):
                continue
            name = id_to_name.get(row.get("documentId"))
            if not name:
                continue
            try:
                page = int(row["page"])
            except (KeyError, TypeError, ValueError):
                continue
            blocks = row.get("blocks") or []
            # Always include `verified` (even None) so the caller sees a MinerU
            # signal at all rather than mistaking absence for "not verified".
            found[f"projects/{slug}/uploads/raw/{name}"] = found.get(
                f"projects/{slug}/uploads/raw/{name}", {}
            )
            found[f"projects/{slug}/uploads/raw/{name}"][page] = {
                "verified": row.get("verified"),
                "block_count": len(blocks) if isinstance(blocks, list) else 0,
            }
        return found
    except Exception:
        return {}
