"""POST /api/catalog/products - add a part by hand. Administrators only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from cbc.modules.catalog.domain.products import ProductCreate, coerce_book_id, derive_sell
from cbc.modules.catalog.infrastructure.collections import products
from cbc.modules.ops.api import audit
from cbc.shared.auth import AdminActor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/products", status_code=201)
async def create_product(body: ProductCreate, actor: AdminActor) -> dict:
    document = coerce_book_id(
        {**body.model_dump(exclude_none=True), "updatedAt": _now(), "updatedBy": actor}
    )

    # A part number is only unique within its manufacturer - Hager's 1234 and
    # Rockwood's 1234 are different parts and both belong in the catalog. But a
    # part added without saying whose it is cannot be told apart from one that is
    # already here, so that is refused rather than quietly becoming a second row.
    if not body.manufacturer:
        clash = await products().find_one({"part": body.part})
        if clash:
            raise HTTPException(
                409,
                f"part {body.part} already exists under "
                f"{clash.get('manufacturer') or 'no manufacturer'}. Give a "
                "manufacturer to add it as a different vendor's part.",
            )
    try:
        result = await products().insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(
            409,
            f"part {body.part} already exists for {body.manufacturer}",
        )

    document["_id"] = result.inserted_id
    await audit.record("catalog.create", actor, {"productId": result.inserted_id}, after=body.part)
    return {**serialise(document), "sellAt": derive_sell(document)}
