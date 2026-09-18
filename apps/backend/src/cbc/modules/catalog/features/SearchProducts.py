"""GET /api/catalog/products - the estimator's own parts, and the price-book pages worth opening.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from cbc.modules.catalog.api import search as catalog_search
from cbc.modules.catalog.domain.products import derive_sell
from cbc.modules.catalog.infrastructure.collections import products

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/products")
async def search_products(
    q: str | None = None,
    division: str | None = None,
    manufacturer: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """The estimator's own parts, and the price-book pages worth opening.

    The two are different things and come back as different lists. A hand-added
    part is a product with a cost. A price book is a PDF: the vendor half returns
    `pages` - where to look and what is on the page - because pre-extracting those
    pages into product rows is what produced an index where 37.8% of the codes
    contained no letter and dates were recorded as part numbers.

    `total` is the full filtered match count; `products` is one page of
    `limit` rows starting at `offset`.
    """
    found = await catalog_search.search(
        q,
        division=division,
        manufacturer=manufacturer,
        limit=limit,
        offset=offset,
    )
    divisions = await products().aggregate(
        [{"$group": {"_id": "$division", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]
    ).to_list(50)

    return {
        **found,
        "products": [
            {**row, "sellAt": row.get("sellAt") if row["source"] == "manual" else derive_sell(row)}
            for row in found["products"]
        ],
        "divisions": [
            {"division": row["_id"], "count": row["n"]} for row in divisions if row["_id"]
        ],
    }
