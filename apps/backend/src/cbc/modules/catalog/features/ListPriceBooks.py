"""GET /api/price-books - every program, with its age and whether it is stale.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.modules.catalog.infrastructure.price_book_view import decorate

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


@router.get("")
async def list_price_books() -> dict[str, Any]:
    books = await price_books().find().sort([("vendor", 1), ("program", 1)]).to_list(200)
    decorated = [await decorate(b) for b in books]
    return {
        "priceBooks": decorated,
        "counts": {
            "total": len(decorated),
            "stale": sum(1 for b in decorated if b["stale"]),
            "undated": sum(1 for b in decorated if b["undated"]),
        },
        "stewardship": {
            "owner": None,
            "cadence": None,
            "note": "NFR-10 is open - no owner or refresh cadence has been assigned.",
        },
    }
