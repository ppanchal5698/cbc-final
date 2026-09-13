"""DELETE /api/price-books/{book_id} - remove a program; its parts are kept and marked orphaned.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from cbc.modules.catalog.infrastructure.collections import price_books, products
from cbc.modules.ops.api import audit, jobs
from cbc.shared.auth import AdminActor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.delete("/{book_id}", status_code=204, response_class=Response)
async def delete_price_book(book_id: str, actor: AdminActor) -> Response:
    """Remove the program. Products priced under it are kept but marked orphaned.

    Deleting a book must not silently vaporise catalog rows a live quote points at.
    """
    book = await price_books().find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    await products().update_many(
        {"priceBookId": book["_id"]},
        {"$set": {"priceBookId": None, "orphanedFrom": book.get("vendor"), "updatedAt": _now()}},
    )

    # Remove what was indexed from this book's PDF, so a deleted catalog stops
    # appearing in search. Queued rather than done inline: the worker is the only
    # writer to the index, and deletion has to be verified, not assumed.
    if book.get("catalogId") or book.get("filename"):
        payload: dict[str, Any] = {
            "filename": book.get("filename"),
            "priceBookId": str(book["_id"]),
        }
        if book.get("catalogId"):
            payload["catalogId"] = book["catalogId"]
        await jobs.enqueue("delete_catalog", payload=payload, actor=actor)
    await price_books().delete_one({"_id": book["_id"]})
    await audit.record(
        "price_book.delete",
        actor,
        {"priceBookId": book["_id"]},
        before=book.get("vendor"),
        note="products retained, marked orphaned",
    )
    return Response(status_code=204)
