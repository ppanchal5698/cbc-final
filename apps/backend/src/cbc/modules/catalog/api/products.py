"""The catalog's parts, for the modules that price and quote them.
"""
from __future__ import annotations

from typing import Any, TypedDict

from cbc.modules.catalog.infrastructure.collections import products
from cbc.shared.mongo import oid


class ProductRef(TypedDict, total=False):
    """A catalog part, as other modules read it.

    Still the stored document at runtime: a TypedDict converts nothing.
    """

    _id: Any
    part: str
    description: str
    division: str
    finish: str
    fireRating: str
    rating: str
    handing: str
    cost: float


async def get(product_id: str) -> ProductRef | None:
    """One part by id. A malformed id raises the ValueError every route answers with a 400."""
    return await products().find_one({"_id": oid(product_id)})


async def by_part(part: str, *, limit: int = 20) -> list[ProductRef]:
    """Every manufacturer's row for this part number, up to `limit`."""
    return await products().find({"part": part}).limit(limit).to_list(limit)
