"""The catalog's parts, for the modules that price and quote them.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from typing import Any, TypedDict

from cbc.modules.catalog.domain import partquery
from cbc.modules.catalog.infrastructure.collections import price_book_entries, price_books, products
from cbc.shared.mongo import oid

# The forms of a specified part to look up, most specific first: whole, then with
# a vendor name and the trailing size and finish tokens dropped one at a time.
part_candidates = partquery.normalize


async def vendor_names() -> list[str]:
    """Every vendor the catalog names, for stripping one off a specified part."""
    return sorted({*await products().distinct("manufacturer"), *await products().distinct("vendorKey")} - {None, ""})


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


async def by_parts(
    parts: Iterable[str], *, limit_each: int = 20, quotable: bool = False
) -> dict[str, list[ProductRef]]:
    """Every manufacturer's rows for each of these part numbers, at most `limit_each` a part.

    One query for a whole bid; `by_part` in a loop was a round trip a door.
    `quotable` keeps only rows a price may be taken from - never an OCR extract.
    """
    wanted = sorted({part for part in parts if part})
    found: dict[str, list[ProductRef]] = {part: [] for part in wanted}
    if not wanted:
        return found
    query: dict[str, Any] = {"part": {"$in": wanted}}
    if quotable:
        query = {"$and": [query, partquery.trust_clause()]}
    async for row in products().find(query):
        rows = found[row["part"]]
        if len(rows) < limit_each:
            rows.append(row)
    return found


async def by_series(prefixes: Iterable[str], *, limit: int = 5000) -> list[ProductRef]:
    """The sized variants of each series - quotable rows whose part extends a prefix
    past a separator: `B-5806` gives `B-5806.99x48`, not `B-580616x18`."""
    wanted = sorted({p for p in prefixes if p and len(p) >= 3})
    if not wanted:
        return []
    series = {"$or": [{"part": {"$regex": f"^{re.escape(p)}[^A-Za-z0-9]"}} for p in wanted]}
    return await products().find({"$and": [series, partquery.trust_clause()]}).to_list(limit)


async def by_vendors(vendor_keys: Iterable[str], *, limit: int = 20000) -> list[ProductRef]:
    """Every quotable row of these vendors - the brands a direct equal may come from."""
    keys = sorted({k for k in vendor_keys if k})
    if not keys:
        return []
    return await products().find({"$and": [{"vendorKey": {"$in": keys}}, partquery.trust_clause()]}).to_list(limit)


async def iter_items() -> AsyncIterator[dict[str, Any]]:
    """Every catalog part, for the memory graph's mirror of the catalog."""
    fields = {"part": 1, "manufacturer": 1, "description": 1, "division": 1, "category": 1,
              "cost": 1, "listPrice": 1, "multiplier": 1, "priceBasis": 1, "availability": 1, "model": 1,
              "priceBookId": 1, "priceBook": 1}
    async for row in products().find({}, fields):
        yield row


async def price_book_summaries() -> list[dict[str, Any]]:
    """Each price book's identity and dates - not its rows."""
    fields = {"vendor": 1, "program": 1, "filename": 1, "kind": 1, "effective": 1, "entries": 1, "isDeleted": 1}
    return await price_books().find({"isDeleted": {"$ne": True}}, fields).to_list(None)


async def list_prices(models: Iterable[str], *, vendor: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Every list price read off a current price book for each model number.

    Only the version each book now points at (`priceBooks.entries.fileSha`):
    rows read off a superseded sheet stay as history and are never priced from.
    """
    wanted = sorted({m for m in models if m})
    found: dict[str, list[dict[str, Any]]] = {m: [] for m in wanted}
    if not wanted:
        return found
    current = [
        {"priceBookId": book["_id"], "fileSha": book["entries"]["fileSha"]}
        async for book in price_books().find({"entries.fileSha": {"$exists": True}, "isDeleted": {"$ne": True}})
    ]
    if not current:
        return found
    query: dict[str, Any] = {"model": {"$in": wanted}, "$or": current}
    if vendor:
        query["vendor"] = vendor.lower()
    async for row in price_book_entries().find(query):
        found[row["model"]].append(row)
    return found
