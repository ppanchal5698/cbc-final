"""What the catalog screen searches: the estimator's own parts, and the price books.

The two halves are no longer the same shape, and pretending otherwise is what this
replaces.

  * **The estimator's own parts** are rows in MongoDB with a part number, a cost
    and a margin. They are products, and they stay editable.
  * **The price books** are PDFs. They used to be pre-extracted into a product
    table so both halves could be listed together - and 37.8% of the codes that
    produced contained no letter at all, dates were recorded as part numbers, and
    one vendor's sheet yielded nothing while reporting success. A row that looked
    like a product but was page furniture was indistinguishable from a real one.

So the vendor half now returns **pages**, not products: where to look, with a
description of what is on the page. Opening it is a click for an estimator and a
`pdf-tools` call for a pricing pass, and either way the number comes off the sheet
rather than out of a table nobody checked.
"""
from __future__ import annotations

import re
from typing import Any

from cbc.db import db, serialise
from cbc.pageindex import basis, query as page_query, store as page_store


async def index_available() -> bool:
    """Whether any catalog has been indexed, for the health endpoint."""
    try:
        return bool(await page_store.list_catalogs())
    except Exception:
        return False


async def search_pages(
    query: str,
    *,
    vendor: str | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Pages of the vendor catalogs worth opening for this query."""
    if not query:
        return []
    found = await page_query.find_pages(query, vendor=vendor, limit=limit)
    return found.get("pages", [])


async def search_manual(
    query: str | None,
    *,
    division: str | None = None,
    manufacturer: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """The estimator's own parts. Editable, and independent of any catalog."""
    mongo: dict[str, Any] = {"seedSource": {"$ne": "price book ingest"}}
    if division:
        mongo["division"] = division
    if manufacturer:
        mongo["manufacturer"] = manufacturer
    if query:
        needle = re.escape(query)  # user input, not a pattern
        mongo["$or"] = [
            {"part": {"$regex": f"^{needle}", "$options": "i"}},
            {"description": {"$regex": needle, "$options": "i"}},
            {"manufacturer": {"$regex": needle, "$options": "i"}},
        ]
    rows = await db.products.find(mongo).sort("part", 1).to_list(limit)
    # A hand-added part keeps cost and list in separate columns the estimator filled
    # in, so there is nothing to disambiguate: its listPrice is a list price.
    return [
        {
            **serialise(row),
            "priceBasis": basis.LIST,
            "priceBasisNote": basis.describe(basis.LIST),
            "netPrice": None,
            "source": "manual",
            "editable": True,
        }
        for row in rows
    ]


async def search(
    query: str | None,
    *,
    division: str | None = None,
    manufacturer: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Both halves, each as what it actually is."""
    import asyncio

    manual, pages = await asyncio.gather(
        search_manual(query, division=division, manufacturer=manufacturer, limit=limit),
        search_pages(query or "", vendor=manufacturer, limit=12),
    )
    indexed = await index_available()
    return {
        "products": manual,
        "pages": pages,
        "total": len(manual),
        "counts": {"manual": len(manual), "pages": len(pages)},
        "indexAvailable": indexed,
        "note": (
            None
            if indexed
            else "The catalog index has not been built yet — only hand-added parts appear. "
                 "Your administrator can rebuild it from Settings."
        ),
        "pagesNote": (
            "These are pages in the vendor price books, not priced lines. Open one "
            "to read what it actually says."
            if pages
            else None
        ),
    }
