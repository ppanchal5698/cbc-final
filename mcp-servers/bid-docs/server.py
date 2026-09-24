#!/usr/bin/env python3
"""bid-docs MCP server — query parsed blocks for uploaded bid PDFs.

READ-ONLY: MONGODB_READONLY_URI only; no write tools; no fallback to the
writable application URI.
"""
from __future__ import annotations

import os
import re
from typing import Any

from bson import ObjectId
from pymongo import MongoClient

from _runtime import serve
from tools import TOOLS

MAX_LIMIT = 50

_FORBIDDEN = ("write", "update", "insert", "upsert", "delete", "create", "set_")
assert not [t for t in TOOLS if any(word in t["name"].lower() for word in _FORBIDDEN)], (
    "bid-docs must expose no write tools"
)


def _readonly_client() -> MongoClient:
    uri = os.environ.get("MONGODB_READONLY_URI")
    if not uri:
        raise RuntimeError(
            "MONGODB_READONLY_URI is required for bid-docs "
            "(refusing to fall back to the writable MONGODB_URI)"
        )
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def _db():
    client = _readonly_client()
    name = os.environ.get("MONGODB_DB", "cbc_opshub")
    return client[name]


def _project(project: str) -> dict[str, Any] | None:
    db = _db()
    query: dict[str, Any]
    if re.fullmatch(r"[0-9a-fA-F]{24}", project or ""):
        query = {"_id": ObjectId(project)}
    else:
        query = {"$or": [{"code": project}, {"slug": project}]}
    return db["bidRequests"].find_one(query)


def _oid(value: str) -> ObjectId:
    return ObjectId(value)


def list_documents(project: str) -> dict[str, Any]:
    bid = _project(project)
    if bid is None:
        return {"error": f"project not found: {project!r}", "documents": []}
    rows = list(
        _db()["documents"].find(
            {"projectId": bid["_id"]},
            {"filename": 1, "pages": 1, "kind": 1, "parse": 1, "contentSha": 1},
        )
    )
    docs = []
    for row in rows:
        parse = row.get("parse") or {}
        docs.append(
            {
                "document_id": str(row["_id"]),
                "filename": row.get("filename"),
                "kind": row.get("kind"),
                "pages": row.get("pages"),
                "parse_state": parse.get("state"),
                "pages_done": parse.get("pagesDone"),
                "backend": (parse.get("settings") or {}).get("backend"),
            }
        )
    return {"project": bid.get("code") or bid.get("slug"), "count": len(docs), "documents": docs}


def get_outline(project: str, document_id: str) -> dict[str, Any]:
    bid = _project(project)
    if bid is None:
        return {"error": f"project not found: {project!r}"}
    try:
        doc_oid = _oid(document_id)
    except Exception:
        return {"error": f"invalid document_id: {document_id!r}"}
    doc = _db()["documents"].find_one({"_id": doc_oid, "projectId": bid["_id"]})
    if doc is None:
        return {"error": f"document not on this bid: {document_id}"}

    pages = list(
        _db()["documentPages"]
        .find({"documentId": doc_oid}, {"page": 1, "blocks": 1, "verified": 1, "pageSize": 1})
        .sort("page", 1)
    )
    outline = []
    for page in pages:
        blocks = page.get("blocks") or []
        title = None
        sheet = None
        for block in blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if sheet is None and (
                re.search(r"\b[a-z]?\d+\.\d+\b", text, re.I)
                or "sheet" in lowered
            ):
                sheet = text.split("\n", 1)[0][:120]
            if title is None and block.get("type") in {"title", "text", "discarded"}:
                if len(text) < 120:
                    title = text
        counts: dict[str, int] = {}
        for block in blocks:
            key = str(block.get("type") or "text")
            counts[key] = counts.get(key, 0) + 1
        outline.append(
            {
                "page": page["page"],
                "page_size": page.get("pageSize"),
                "verified": page.get("verified"),
                "title": title,
                "sheet": sheet,
                "block_count": len(blocks),
                "types": counts,
            }
        )
    return {
        "document_id": document_id,
        "filename": doc.get("filename"),
        "pages": outline,
    }


def search_blocks(
    project: str,
    query: str,
    document_id: str | None = None,
    types: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    bid = _project(project)
    if bid is None:
        return {"error": f"project not found: {project!r}", "hits": []}
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 20

    filt: dict[str, Any] = {"projectId": bid["_id"], "$text": {"$search": query}}
    if document_id:
        try:
            filt["documentId"] = _oid(document_id)
        except Exception:
            return {"error": f"invalid document_id: {document_id!r}", "hits": []}

    wanted = {t.lower() for t in (types or []) if t}
    hits: list[dict[str, Any]] = []
    cursor = (
        _db()["documentPages"]
        .find(filt, {"score": {"$meta": "textScore"}, "page": 1, "blocks": 1, "pageSize": 1, "documentId": 1})
        .sort([("score", {"$meta": "textScore"})])
        .limit(limit * 3)
    )
    needle = query.lower()
    for row in cursor:
        for block in row.get("blocks") or []:
            if wanted and str(block.get("type", "")).lower() not in wanted:
                continue
            text = block.get("text") or ""
            if needle not in text.lower() and query not in text:
                # $text matched the page; keep blocks that still look relevant
                if not any(tok in text.lower() for tok in needle.split() if len(tok) > 2):
                    continue
            hits.append(
                {
                    "document_id": str(row["documentId"]),
                    "page": row["page"],
                    "page_size": row.get("pageSize"),
                    "n": block.get("n"),
                    "type": block.get("type"),
                    "text": text[:500],
                    "bbox": block.get("bbox"),
                }
            )
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    return {"query": query, "count": len(hits), "hits": hits}


def get_page_blocks(
    project: str,
    document_id: str,
    page: int,
    types: list[str] | None = None,
    start: int = 0,
    max_chars: int = 20000,
) -> dict[str, Any]:
    bid = _project(project)
    if bid is None:
        return {"error": f"project not found: {project!r}"}
    try:
        doc_oid = _oid(document_id)
        page = int(page)
        start = max(0, int(start))
        max_chars = max(100, min(int(max_chars), 200000))
    except Exception as exc:
        return {"error": str(exc)}

    row = _db()["documentPages"].find_one({"documentId": doc_oid, "page": page})
    if row is None:
        return {
            "error": f"no parsed blocks for page {page}",
            "note": "Use pdf-tools for unparsed pages.",
        }
    # Ensure the document belongs to this bid
    doc = _db()["documents"].find_one({"_id": doc_oid, "projectId": bid["_id"]})
    if doc is None:
        return {"error": f"document not on this bid: {document_id}"}

    blocks = list(row.get("blocks") or [])
    if types:
        wanted = {t.lower() for t in types if t}
        blocks = [b for b in blocks if str(b.get("type", "")).lower() in wanted]

    sliced: list[dict[str, Any]] = []
    chars = 0
    next_start = None
    for index, block in enumerate(blocks):
        if index < start:
            continue
        text = str(block.get("text") or "")
        if sliced and chars + len(text) > max_chars:
            next_start = index
            break
        sliced.append(
            {
                "n": block.get("n"),
                "type": block.get("type"),
                "text": text,
                "bbox": block.get("bbox"),
                "html": block.get("html"),
            }
        )
        chars += len(text)

    return {
        "document_id": document_id,
        "page": page,
        "page_size": row.get("pageSize"),
        "verified": row.get("verified"),
        "blocks": sliced,
        "start": start,
        "next": next_start,
        "total": len(blocks),
        "note": (
            "Crop with pdf-tools.get_page_image(file_path, page, region=bbox) "
            "only when a value is unclear — never open a full page image of a parsed page."
        ),
    }


HANDLERS = {
    "list_documents": list_documents,
    "get_outline": get_outline,
    "search_blocks": search_blocks,
    "get_page_blocks": get_page_blocks,
}
assert set(HANDLERS) == {t["name"] for t in TOOLS}


def _demo() -> None:
    """Smoke against whatever is in the RO database (may be empty)."""
    if not os.environ.get("MONGODB_READONLY_URI"):
        print("bid-docs demo SKIPPED - MONGODB_READONLY_URI is not set")
        return
    listed = list_documents("CBC-000000")
    assert "documents" in listed or "error" in listed


if __name__ == "__main__":
    serve("bid-docs", TOOLS, HANDLERS, demo=_demo)
