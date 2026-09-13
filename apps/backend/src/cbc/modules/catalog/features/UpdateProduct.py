"""PATCH /api/catalog/products/{product_id} - change a part. Administrators only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.catalog.domain.products import ProductUpdate, coerce_book_id, derive_sell
from cbc.modules.catalog.infrastructure.collections import products
from cbc.modules.ops.api import audit
from cbc.shared.auth import AdminActor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate, actor: AdminActor) -> dict:
    product = await products().find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(404, "product not found")

    changes = coerce_book_id(body.model_dump(exclude_unset=True))
    if not changes:
        return {**serialise(product), "sellAt": derive_sell(product)}

    await products().update_one(
        {"_id": product["_id"]}, {"$set": {**changes, "updatedAt": _now(), "updatedBy": actor}}
    )
    await audit.record(
        "catalog.update",
        actor,
        {"productId": product["_id"]},
        before={k: product.get(k) for k in changes},
        after=changes,
    )
    updated = await products().find_one({"_id": product["_id"]})
    return {**serialise(updated), "sellAt": derive_sell(updated)}
