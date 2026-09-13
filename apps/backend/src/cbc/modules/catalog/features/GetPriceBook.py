"""GET /api/price-books/{book_id} - one program and the parts priced under it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.catalog.infrastructure.collections import price_books, products
from cbc.modules.catalog.infrastructure.price_book_view import decorate
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


@router.get("/{book_id}")
async def get_price_book(book_id: str) -> dict[str, Any]:
    book = await price_books().find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    parts = await products().find({"priceBookId": book["_id"]}).sort("part", 1).to_list(500)
    part_count = await products().count_documents({"priceBookId": book["_id"]})
    return {"priceBook": await decorate(book), "parts": serialise(parts), "partCount": part_count}
