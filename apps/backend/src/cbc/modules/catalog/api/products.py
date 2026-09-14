"""The catalog's parts, for the modules that price and quote them.
"""
from __future__ import annotations

from collections.abc import Iterable
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


async def by_parts(parts: Iterable[str], *, limit_each: int = 20) -> dict[str, list[ProductRef]]:
    """Every manufacturer's rows for each of these part numbers, at most `limit_each` a part.

    One query for a whole bid; `by_part` in a loop was a round trip a door.
    """
    wanted = sorted({part for part in parts if part})
    found: dict[str, list[ProductRef]] = {part: [] for part in wanted}
    if not wanted:
        return found
    async for row in products().find({"part": {"$in": wanted}}):
        rows = found[row["part"]]
        if len(rows) < limit_each:
            rows.append(row)
    return found
