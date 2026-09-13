"""PATCH /api/price-books/{book_id} - change a program; a new multiplier reprices its list-priced parts.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.catalog.domain.price_books import PriceBookUpdate
from cbc.modules.catalog.infrastructure.collections import price_books, products
from cbc.modules.catalog.infrastructure.price_book_view import decorate
from cbc.modules.ops.api import audit
from cbc.modules.catalog.api.pageindex import basis
from cbc.modules.pricing.api.reference_library import sync_vendor_categories
from cbc.shared.auth import AdminActor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/price-books", tags=["price-books"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("/{book_id}")
async def update_price_book(book_id: str, body: PriceBookUpdate, actor: AdminActor) -> dict:
    book = await price_books().find_one({"_id": oid(book_id)})
    if not book:
        raise HTTPException(404, "price book not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return await decorate(book)

    await price_books().update_one({"_id": book["_id"]}, {"$set": {**changes, "updatedAt": _now()}})

    if "categories" in changes and changes["categories"] is not None:
        await asyncio.to_thread(
            sync_vendor_categories, book.get("vendor", ""), changes["categories"]
        )

    # A changed multiplier reprices every part on this program - but only where
    # there is a list price to multiply. A vendor bought on a flat net program
    # publishes costs, and multiplying one of those discounts it a second time:
    # a Bobrick line at its 2017 net would be quoted at a fraction of what CBC
    # pays. Ingest keeps nets out of `listPrice` for exactly this reason; these
    # two filters are the belt to that braces, and they also cover rows written
    # before the basis was recorded.
    #
    # An *unknown* basis is deliberately still repriced. It means no multiplier
    # has been transcribed for the vendor, not that the sheet quotes nets - and a
    # hand-built book is somebody stating outright that they entered a list price.
    repriced: int | None = None
    if "multiplier" in changes and changes["multiplier"]:
        if basis.price_basis(book.get("filename"), book.get("vendor")) == basis.NET:
            repriced = 0
        else:
            result = await products().update_many(
                {
                    "priceBookId": book["_id"],
                    "listPrice": {"$ne": None},
                    "priceBasis": {"$ne": basis.NET},
                },
                [
                    {
                        "$set": {
                            "multiplier": changes["multiplier"],
                            "cost": {
                                "$round": [
                                    {"$multiply": ["$listPrice", changes["multiplier"]]}, 2
                                ]
                            },
                            "updatedAt": _now(),
                            "updatedBy": actor,
                        }
                    }
                ],
            )
            repriced = result.modified_count

    await audit.record(
        "price_book.update",
        actor,
        {"priceBookId": book["_id"]},
        before={k: book.get(k) for k in changes},
        after={**changes, **({"repricedParts": repriced} if repriced is not None else {})},
    )
    return await decorate(await price_books().find_one({"_id": book["_id"]}))
