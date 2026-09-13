"""DELETE /api/catalog/products/{product_id} - remove a part. Administrators only.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from cbc.modules.catalog.infrastructure.collections import products
from cbc.modules.ops.api import audit
from cbc.shared.auth import AdminActor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.delete("/products/{product_id}", status_code=204, response_class=Response)
async def delete_product(product_id: str, actor: AdminActor) -> Response:
    product = await products().find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(404, "product not found")

    await products().delete_one({"_id": product["_id"]})
    await audit.record(
        "catalog.delete", actor, {"productId": product["_id"]}, before=product.get("part")
    )
    return Response(status_code=204)
