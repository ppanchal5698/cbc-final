"""GET /api/price-books/{book_id}/file - the sheet as it was uploaded.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.services import storage  # ponytail: legacy kernel; the file tree moves to shared/ in Phase 4
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


@router.get("/{book_id}/file")
async def download_price_book(book_id: str) -> FileResponse:
    book = await price_books().find_one({"_id": oid(book_id)})
    if not book or not book.get("path"):
        raise HTTPException(404, "no file attached to this price book")

    path = storage.absolute(book["path"])
    if not path.exists():
        raise HTTPException(410, f"file missing on disk: {book['path']}")
    return FileResponse(path, filename=book.get("filename") or path.name)
