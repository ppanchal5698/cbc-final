"""GET /api/projects/{code}/documents/{id}/pages/{n}/blocks - MinerU page blocks."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from cbc.modules.intake.infrastructure.collections import document_pages
from cbc.modules.intake.infrastructure.document_access import find_on_bid
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


@router.get("/{document_id}/pages/{page_number}/blocks")
async def list_page_blocks(
    code: str,
    document_id: str,
    page_number: int,
    types: str | None = Query(default=None, description="Comma-separated block types"),
    start: int = Query(default=0, ge=0),
    max_chars: int = Query(default=20000, ge=100, le=200000),
) -> dict:
    document = await find_on_bid(code, document_id)
    row = await document_pages().find_one(
        {"documentId": document["_id"], "page": page_number}
    )
    if row is None:
        raise HTTPException(404, f"no parsed blocks for page {page_number}")

    blocks = list(row.get("blocks") or [])
    if types:
        wanted = {t.strip().lower() for t in types.split(",") if t.strip()}
        blocks = [b for b in blocks if str(b.get("type", "")).lower() in wanted]

    # Cursor by block index; stop when cumulative text exceeds max_chars.
    sliced: list[dict] = []
    chars = 0
    next_start = None
    for index, block in enumerate(blocks):
        if index < start:
            continue
        text = str(block.get("text") or "")
        if sliced and chars + len(text) > max_chars:
            next_start = index
            break
        sliced.append(block)
        chars += len(text)
    else:
        next_start = None

    return {
        "documentId": str(document["_id"]),
        "page": page_number,
        "pageSize": row.get("pageSize"),
        "verified": row.get("verified"),
        "parser": row.get("parser"),
        "blocks": serialise(sliced),
        "start": start,
        "next": next_start,
        "total": len(blocks),
    }
