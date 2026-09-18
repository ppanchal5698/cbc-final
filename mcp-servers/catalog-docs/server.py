#!/usr/bin/env python3
"""catalog-docs MCP server — query MinerU-parsed blocks for price books.

READ-ONLY: MONGODB_READONLY_URI only; no write tools; no fallback to the
writable application URI.
"""
from __future__ import annotations

import os
from typing import Any

from bson import ObjectId
from pymongo import MongoClient

from _runtime import serve
from tools import TOOLS

MAX_LIMIT = 50

_FORBIDDEN = ("write", "update", "insert", "upsert", "delete", "create", "set_")
assert not [t for t in TOOLS if any(word in t["name"].lower() for word in _FORBIDDEN)], (
    "catalog-docs must expose no write tools"
)


def _readonly_client() -> MongoClient:
    uri = os.environ.get("MONGODB_READONLY_URI")
    if not uri:
        raise RuntimeError(
            "MONGODB_READONLY_URI is required for catalog-docs "
            "(refusing to fall back to the writable MONGODB_URI)"
        )
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def _db():
    client = _readonly_client()
    name = os.environ.get("MONGODB_DB", "cbc_opshub")
    return client[name]


def _oid(value: str) -> ObjectId:
    return ObjectId(value)


def list_catalogs_parsed(
    vendor: str | None = None, kind: str | None = None
) -> dict[str, Any]:
    filt: dict[str, Any] = {"filename": {"$exists": True, "$ne": None}}
    if vendor:
        filt["vendor"] = vendor.strip().lower()
    if kind:
        filt["kind"] = kind
    rows = list(
        _db()["priceBooks"].find(
            filt,
            {
                "vendor": 1,
                "program": 1,
                "filename": 1,
                "kind": 1,
                "catalogId": 1,
                "parse": 1,
            },
        )
    )
    catalogs = []
    for row in rows:
        parse = row.get("parse") or {}
        catalog_id = row.get("catalogId") or (
            (row.get("filename") or "").rsplit(".", 1)[0].lower().replace(" ", "_")
            if row.get("filename")
            else None
        )
        page_count = _db()["catalogPages"].count_documents(
            {"priceBookId": row["_id"]}
        )
        if page_count == 0 and catalog_id:
            page_count = _db()["multiplierPages"].count_documents(
                {"sheetId": catalog_id}
            )
        catalogs.append(
            {
                "price_book_id": str(row["_id"]),
                "catalog_id": catalog_id,
                "vendor": row.get("vendor"),
                "program": row.get("program"),
                "filename": row.get("filename"),
                "kind": row.get("kind") or "price_book",
                "parse_state": parse.get("state"),
                "pages_done": parse.get("pagesDone"),
                "pages": parse.get("pages"),
                "parsed_page_count": page_count,
                "backend": (parse.get("settings") or {}).get("backend"),
            }
        )
    return {"count": len(catalogs), "catalogs": catalogs}


def _page_filter(
    *,
    catalog_id: str | None,
    price_book_id: str | None,
    source: str,
) -> tuple[str, dict[str, Any]] | dict[str, Any]:
    """Return (collection, filter) or an error dict."""
    source = (source or "catalog").lower()
    if source == "multiplier":
        coll = "multiplierPages"
        filt: dict[str, Any] = {}
        if catalog_id:
            filt["sheetId"] = catalog_id
        elif price_book_id:
            try:
                filt["priceBookId"] = _oid(price_book_id)
            except Exception:
                return {"error": f"invalid price_book_id: {price_book_id!r}"}
        else:
            return {"error": "catalog_id or price_book_id required"}
        return coll, filt

    coll = "catalogPages"
    filt = {}
    if price_book_id:
        try:
            filt["priceBookId"] = _oid(price_book_id)
        except Exception:
            return {"error": f"invalid price_book_id: {price_book_id!r}"}
    elif catalog_id:
        filt["catalogId"] = catalog_id
    else:
        return {"error": "catalog_id or price_book_id required"}
    return coll, filt


def get_outline(
    catalog_id: str | None = None,
    price_book_id: str | None = None,
    source: str = "catalog",
) -> dict[str, Any]:
    resolved = _page_filter(
        catalog_id=catalog_id, price_book_id=price_book_id, source=source
    )
    if isinstance(resolved, dict):
        return resolved
    coll, filt = resolved
    pages = list(
        _db()[coll]
        .find(filt, {"page": 1, "blocks": 1, "verified": 1, "pageSize": 1, "filename": 1, "filePath": 1})
        .sort("page", 1)
    )
    if not pages:
        return {
            "error": "no parsed pages",
            "note": "Use catalog.find_pages until parse_catalog finishes.",
        }
    outline = []
    for page in pages:
        blocks = page.get("blocks") or []
        title = None
        for block in blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue
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
                "block_count": len(blocks),
                "types": counts,
            }
        )
    return {
        "catalog_id": catalog_id,
        "price_book_id": price_book_id,
        "filename": pages[0].get("filename"),
        "file_path": pages[0].get("filePath"),
        "pages": outline,
    }


def _hit_from_block(row: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_id": row.get("catalogId") or row.get("sheetId"),
        "price_book_id": str(row["priceBookId"]) if row.get("priceBookId") else None,
        "vendor": row.get("vendor"),
        "filename": row.get("filename"),
        "file_path": row.get("filePath"),
        "pdf_page": row["page"],
        "page": row["page"],
        "page_size": row.get("pageSize"),
        "n": block.get("n"),
        "type": block.get("type"),
        "text": (block.get("text") or "")[:500],
        "html": (block.get("html") or "")[:500] or None,
        "bbox": block.get("bbox"),
    }


def search_blocks(
    query: str,
    catalog_id: str | None = None,
    vendor: str | None = None,
    source: str = "both",
    types: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 20

    sources = []
    src = (source or "both").lower()
    if src in {"catalog", "both"}:
        sources.append("catalogPages")
    if src in {"multiplier", "both"}:
        sources.append("multiplierPages")

    wanted = {t.lower() for t in (types or []) if t}
    needle = query.lower()
    hits: list[dict[str, Any]] = []

    for coll in sources:
        filt: dict[str, Any] = {"$text": {"$search": query}}
        if catalog_id:
            if coll == "multiplierPages":
                filt["sheetId"] = catalog_id
            else:
                filt["catalogId"] = catalog_id
        if vendor:
            filt["vendor"] = vendor.strip().lower()

        cursor = (
            _db()[coll]
            .find(
                filt,
                {
                    "score": {"$meta": "textScore"},
                    "page": 1,
                    "blocks": 1,
                    "pageSize": 1,
                    "catalogId": 1,
                    "sheetId": 1,
                    "priceBookId": 1,
                    "vendor": 1,
                    "filename": 1,
                    "filePath": 1,
                },
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit * 3)
        )
        for row in cursor:
            for block in row.get("blocks") or []:
                if wanted and str(block.get("type", "")).lower() not in wanted:
                    continue
                text = block.get("text") or ""
                html = block.get("html") or ""
                blob = f"{text}\n{html}"
                if needle not in blob.lower() and query not in blob:
                    if not any(
                        tok in blob.lower() for tok in needle.split() if len(tok) > 2
                    ):
                        continue
                hits.append(_hit_from_block(row, block))
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    note = None
    if not hits:
        note = (
            "No parsed-block hits. If parse_state is not parsed, use "
            "catalog.find_pages (pageIndex) as fallback."
        )
    return {"query": query, "count": len(hits), "hits": hits, "note": note}


def get_page_blocks(
    page: int,
    catalog_id: str | None = None,
    price_book_id: str | None = None,
    source: str = "catalog",
    types: list[str] | None = None,
    start: int = 0,
    max_chars: int = 20000,
) -> dict[str, Any]:
    try:
        page = int(page)
        start = max(0, int(start))
        max_chars = max(100, min(int(max_chars), 200000))
    except Exception as exc:
        return {"error": str(exc)}

    resolved = _page_filter(
        catalog_id=catalog_id, price_book_id=price_book_id, source=source
    )
    if isinstance(resolved, dict):
        return resolved
    coll, filt = resolved
    filt = {**filt, "page": page}
    row = _db()[coll].find_one(filt)
    if row is None:
        return {
            "error": f"no parsed blocks for page {page}",
            "note": "Use catalog.find_pages + pdf-tools for unparsed pages.",
        }

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
        "catalog_id": row.get("catalogId") or row.get("sheetId"),
        "price_book_id": str(row["priceBookId"]) if row.get("priceBookId") else None,
        "page": page,
        "page_size": row.get("pageSize"),
        "verified": row.get("verified"),
        "file_path": row.get("filePath"),
        "filename": row.get("filename"),
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
    "list_catalogs_parsed": list_catalogs_parsed,
    "get_outline": get_outline,
    "search_blocks": search_blocks,
    "get_page_blocks": get_page_blocks,
}
assert set(HANDLERS) == {t["name"] for t in TOOLS}


def _demo() -> None:
    if not os.environ.get("MONGODB_READONLY_URI"):
        print("catalog-docs demo SKIPPED - MONGODB_READONLY_URI is not set")
        return
    listed = list_catalogs_parsed()
    assert "catalogs" in listed


if __name__ == "__main__":
    serve("catalog-docs", TOOLS, HANDLERS, demo=_demo)
