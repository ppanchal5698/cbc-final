"""Product catalog - the parts CBC can quote.

Claude maintains the bulk of this through price-book ingestion; the estimator can
search, add, edit and remove by hand. The search endpoint also backs the "add
anything the drawings do not carry" composer on the extraction screen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from cbc.db import db, oid, serialise
from cbc.http.deps import Actor, AdminActor
from cbc.schemas import ProductCreate, ProductUpdate
from cbc.services import audit, catalog_search, pricing

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _derive_sell(product: dict[str, Any]) -> float | None:
    """Sell follows the division's margin divisor unless a price is set explicitly."""
    if product.get("sellAt") is not None:
        return product["sellAt"]
    if product.get("cost") is None:
        return None
    priced = pricing.price_line(
        cost=product["cost"], margin=None, qty=1, division=product.get("division")
    )
    return priced["sell"]


@router.get("/products")
async def search_products(
    q: str | None = None,
    division: str | None = None,
    manufacturer: str | None = None,
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    """The estimator's own parts, and the price-book pages worth opening.

    The two are different things and come back as different lists. A hand-added
    part is a product with a cost. A price book is a PDF: the vendor half returns
    `pages` - where to look and what is on the page - because pre-extracting those
    pages into product rows is what produced an index where 37.8% of the codes
    contained no letter and dates were recorded as part numbers.
    """
    found = await catalog_search.search(
        q, division=division, manufacturer=manufacturer, limit=limit
    )
    divisions = await db.products.aggregate(
        [{"$group": {"_id": "$division", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]
    ).to_list(50)

    return {
        **found,
        "products": [
            {**row, "sellAt": row.get("sellAt") if row["source"] == "manual" else _derive_sell(row)}
            for row in found["products"]
        ],
        "divisions": [
            {"division": row["_id"], "count": row["n"]} for row in divisions if row["_id"]
        ],
    }


@router.get("/products/{product_id}")
async def get_product(product_id: str) -> dict[str, Any]:
    product = await db.products.find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(404, "product not found")

    book = None
    if product.get("priceBookId"):
        book = await db.price_books.find_one({"_id": product["priceBookId"]})

    return {
        "product": {**serialise(product), "sellAt": _derive_sell(product)},
        "priceBook": serialise(book) if book else None,
        "marginBand": pricing.band_for_division(product.get("division")),
    }


def _coerce_book_id(changes: dict[str, Any]) -> dict[str, Any]:
    """Store priceBookId as an ObjectId - the price-book routes query it as one."""
    if changes.get("priceBookId"):
        changes["priceBookId"] = oid(changes["priceBookId"])
    return changes


@router.post("/products", status_code=201)
async def create_product(body: ProductCreate, actor: AdminActor) -> dict:
    document = _coerce_book_id(
        {**body.model_dump(exclude_none=True), "updatedAt": _now(), "updatedBy": actor}
    )

    # A part number is only unique within its manufacturer - Hager's 1234 and
    # Rockwood's 1234 are different parts and both belong in the catalog. But a
    # part added without saying whose it is cannot be told apart from one that is
    # already here, so that is refused rather than quietly becoming a second row.
    if not body.manufacturer:
        clash = await db.products.find_one({"part": body.part})
        if clash:
            raise HTTPException(
                409,
                f"part {body.part} already exists under "
                f"{clash.get('manufacturer') or 'no manufacturer'}. Give a "
                "manufacturer to add it as a different vendor's part.",
            )
    try:
        result = await db.products.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(
            409,
            f"part {body.part} already exists for {body.manufacturer}",
        )

    document["_id"] = result.inserted_id
    await audit.record("catalog.create", actor, {"productId": result.inserted_id}, after=body.part)
    return {**serialise(document), "sellAt": _derive_sell(document)}


@router.patch("/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate, actor: AdminActor) -> dict:
    product = await db.products.find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(404, "product not found")

    changes = _coerce_book_id(body.model_dump(exclude_unset=True))
    if not changes:
        return {**serialise(product), "sellAt": _derive_sell(product)}

    await db.products.update_one(
        {"_id": product["_id"]}, {"$set": {**changes, "updatedAt": _now(), "updatedBy": actor}}
    )
    await audit.record(
        "catalog.update",
        actor,
        {"productId": product["_id"]},
        before={k: product.get(k) for k in changes},
        after=changes,
    )
    updated = await db.products.find_one({"_id": product["_id"]})
    return {**serialise(updated), "sellAt": _derive_sell(updated)}


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: str, actor: AdminActor) -> None:
    product = await db.products.find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(404, "product not found")

    await db.products.delete_one({"_id": product["_id"]})
    await audit.record(
        "catalog.delete", actor, {"productId": product["_id"]}, before=product.get("part")
    )
