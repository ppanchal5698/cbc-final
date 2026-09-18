"""POST /api/price-books/{book_id}/file - attach the sheet and queue it for indexing.

Uploading a book enqueues its indexing, so the next bid Claude prices is using the
sheet purchasing just loaded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.modules.catalog.infrastructure.price_book_view import decorate
from cbc.modules.ops.api import audit, jobs
from cbc.modules.catalog.api.pageindex import store as catalog_store
from cbc.shared import storage
from cbc.shared.auth import Actor
from cbc.shared.config import settings
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


PDF_MAGIC = b"%PDF-"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/{book_id}/file", status_code=201)
async def upload_price_book_file(
    book_id: str,
    actor: Actor,
    file: UploadFile = File(...),
) -> dict:
    """Attach the sheet and ask Claude to read it into the catalog."""
    book = await price_books().find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    settings.pricebook_dir.mkdir(parents=True, exist_ok=True)
    target = storage.unique_filename(settings.pricebook_dir, file.filename or "pricebook.pdf")
    try:
        size = await storage.receive_upload(
            file, target, settings.max_upload_bytes, magic=PDF_MAGIC
        )
    except ValueError as exc:
        detail = str(exc)
        if "exceeds" in detail:
            status = 413
        elif "malware" in detail.lower() or "scanner" in detail.lower():
            status = 422
        else:
            status = 415
        raise HTTPException(status, detail) from exc

    # A new sheet supersedes the one in force, and purchasing needs to see what
    # it replaced and when (auditability.md: a stale sheet must be visible as
    # stale, not silently gone). Push the outgoing one onto the book's own
    # history rather than inventing a collection for it - the file itself is
    # still on disk at the recorded path.
    superseded = (
        [
            {
                "filename": book.get("filename"),
                "path": book.get("path"),
                "bytes": book.get("bytes"),
                "effective": book.get("effective"),
                "uploadedAt": book.get("uploadedAt"),
                "supersededAt": _now(),
                "supersededBy": actor,
            }
        ]
        if book.get("filename")
        else []
    )

    await price_books().update_one(
        {"_id": book["_id"]},
        {
            "$set": {
                "filename": target.name,
                "path": storage.relative(target),
                "bytes": size,
                "uploadedAt": _now(),
                "updatedAt": _now(),
            },
            **({"$push": {"sheetHistory": {"$each": superseded}}} if superseded else {}),
        },
    )

    # Deterministic extraction into the search index. `ingest_pricebook` - the
    # Claude pass - remains available as the adapter of last resort for a layout
    # the generic extractor cannot read, but it is no longer the default: it costs
    # minutes and tokens per book to do what parsing does in seconds.
    file_sha = catalog_store.file_hash(target)
    job = await jobs.enqueue(
        "index_catalog",
        payload={
            "priceBookId": str(book["_id"]),
            "filename": target.name,
            "fileSha": file_sha,
        },
        actor=actor,
    )

    # MinerU block parse (catalogPages / multiplierPages) — parallel to bid
    # parse_document. Soft: skipped when PARSER_URL is empty.
    from cbc.modules.ops.api import parsing_config

    parse_resolved = await parsing_config.load_stored()
    parse_job = None
    if parsing_config.enabled(parse_resolved):
        kind = (book.get("kind") or "price_book").strip().lower()
        parse_type = (
            "parse_multiplier" if kind == "multiplier_sheet" else "parse_catalog"
        )
        await price_books().update_one(
            {"_id": book["_id"]},
            {"$set": {"parse": {"state": "queued"}, "updatedAt": _now()}},
        )
        parse_job = await jobs.enqueue(
            parse_type,
            payload={
                "priceBookId": str(book["_id"]),
                "filename": target.name,
                "fileSha": file_sha,
                "catalogId": book.get("catalogId")
                or catalog_store.catalog_id_for(target.name),
            },
            actor=actor,
        )

    await audit.record("price_book.upload", actor, {"priceBookId": book["_id"]}, after=target.name)
    response: dict[str, Any] = {
        "priceBook": await decorate(await price_books().find_one({"_id": book["_id"]})),
        "job": serialise(job),
    }
    if parse_job is not None:
        response["parseJob"] = serialise(parse_job)
    return response
