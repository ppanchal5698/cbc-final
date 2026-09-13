"""POST /api/price-books - open a program before its sheet is uploaded.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from cbc.modules.catalog.domain.price_books import PriceBookCreate
from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.modules.catalog.infrastructure.price_book_view import decorate
from cbc.modules.ops.api import audit
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", status_code=201)
async def create_price_book(body: PriceBookCreate, actor: Actor) -> dict:
    document = {**body.model_dump(exclude_none=True), "partCount": 0, "updatedAt": _now()}
    result = await price_books().insert_one(document)
    document["_id"] = result.inserted_id
    await audit.record(
        "price_book.create", actor, {"priceBookId": result.inserted_id}, after=body.vendor
    )
    return await decorate(document)
