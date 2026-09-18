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

from typing import Any

from cbc.modules.catalog.domain import partquery
from cbc.modules.catalog.infrastructure.collections import products
from cbc.shared.mongo import serialise
from cbc.modules.catalog.api.pageindex import basis, query as page_query, store as page_store


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


def _manual_filter(
    query: str | None,
    *,
    division: str | None = None,
    manufacturer: str | None = None,
    text: bool = True,
) -> dict[str, Any]:
    """The estimator's own parts, matching `query`.

    `text=True` uses the `product_search` index; `text=False` is the regex shape,
    for the fallback when a query has no whole-word the index can see.
    """
    mongo: dict[str, Any] = {"seedSource": {"$ne": partquery.INGEST_SEED}}
    if division:
        mongo["division"] = division
    if manufacturer:
        mongo["manufacturer"] = manufacturer
    if not query:
        return mongo
    build = partquery.text_filter if text else partquery.regex_filter
    # `include_ingest` because the seedSource rule above is this screen's own and
    # is stricter about nothing: it already excludes the same rows.
    return {"$and": [mongo, build(query, include_ingest=True)]}


async def search_manual(
    query: str | None,
    *,
    division: str | None = None,
    manufacturer: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """The estimator's own parts. Editable, and independent of any catalog.

    Returns `(page_rows, total_matching)` so callers can paginate without
    treating the page length as the catalog size.
    """
    # Precise first. An estimator searching this screen usually types a part
    # number, and `$text` tokenises `TEST-NET-1` into TEST / NET / 1 - which
    # matches every neighbouring part, and since the page is ordered by `part`
    # rather than by relevance the top row stops being the one asked for.
    # `$text` earns its place on a descriptive query, where the anchored regex
    # finds nothing at all.
    mongo = _manual_filter(query, division=division, manufacturer=manufacturer, text=False)
    total = await products().count_documents(mongo)
    if query and not total:
        mongo = _manual_filter(query, division=division, manufacturer=manufacturer, text=True)
        total = await products().count_documents(mongo)
    rows = (
        await products()
        .find(mongo)
        .sort("part", 1)
        .skip(max(0, offset))
        .limit(limit)
        .to_list(limit)
    )
    # A hand-added part keeps cost and list in separate columns the estimator filled
    # in, so there is nothing to disambiguate: its listPrice is a list price.
    page = [
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
    return page, total


async def search(
    query: str | None,
    *,
    division: str | None = None,
    manufacturer: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Both halves, each as what it actually is."""
    import asyncio

    (manual, total), pages = await asyncio.gather(
        search_manual(
            query,
            division=division,
            manufacturer=manufacturer,
            limit=limit,
            offset=offset,
        ),
        search_pages(query or "", vendor=manufacturer, limit=12),
    )
    indexed = await index_available()
    return {
        "products": manual,
        "pages": pages,
        "total": total,
        "counts": {"manual": total, "pages": len(pages)},
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
