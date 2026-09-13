"""POST /api/price-books/{book_id}/mark-reviewed - record that purchasing checked the program today.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.modules.catalog.infrastructure.price_book_view import decorate
from cbc.modules.ops.api import audit
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/{book_id}/mark-reviewed")
async def mark_reviewed(book_id: str, actor: Actor) -> dict:
    book = await price_books().find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    today = date.today().isoformat()
    await price_books().update_one(
        {"_id": book["_id"]}, {"$set": {"lastReviewed": today, "updatedAt": _now()}}
    )
    await audit.record("price_book.reviewed", actor, {"priceBookId": book["_id"]}, after=today)
    return await decorate(await price_books().find_one({"_id": book["_id"]}))
