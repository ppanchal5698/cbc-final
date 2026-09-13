"""GET /api/catalog/products/{product_id} - one part, its price book and its margin band.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.catalog.domain.products import derive_sell
from cbc.modules.catalog.infrastructure.collections import price_books, products
from cbc.services import pricing  # ponytail: margin divisors belong to the pricing module (step 3.8)
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/products/{product_id}")
async def get_product(product_id: str) -> dict[str, Any]:
    product = await products().find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(404, "product not found")

    book = None
    if product.get("priceBookId"):
        book = await price_books().find_one({"_id": product["priceBookId"]})

    return {
        "product": {**serialise(product), "sellAt": derive_sell(product)},
        "priceBook": serialise(book) if book else None,
        "marginBand": pricing.band_for_division(product.get("division")),
    }
