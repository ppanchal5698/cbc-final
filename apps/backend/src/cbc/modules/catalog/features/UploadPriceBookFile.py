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
from cbc.pageindex import store as catalog_store
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

    await price_books().update_one(
        {"_id": book["_id"]},
        {
            "$set": {
                "filename": target.name,
                "path": storage.relative(target),
                "bytes": size,
                "uploadedAt": _now(),
                "updatedAt": _now(),
            }
        },
    )

    # Deterministic extraction into the search index. `ingest_pricebook` - the
    # Claude pass - remains available as the adapter of last resort for a layout
    # the generic extractor cannot read, but it is no longer the default: it costs
    # minutes and tokens per book to do what parsing does in seconds.
    job = await jobs.enqueue(
        "index_catalog",
        payload={
            "priceBookId": str(book["_id"]),
            "filename": target.name,
            "fileSha": catalog_store.file_hash(target),
        },
        actor=actor,
    )

    await audit.record("price_book.upload", actor, {"priceBookId": book["_id"]}, after=target.name)
    response: dict[str, Any] = {
        "priceBook": await decorate(await price_books().find_one({"_id": book["_id"]})),
        "job": serialise(job),
    }
    return response
