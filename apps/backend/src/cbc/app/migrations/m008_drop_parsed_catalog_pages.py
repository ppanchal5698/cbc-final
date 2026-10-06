"""Drop catalogPages and multiplierPages.

They held price-book pages written by a parser the stack no longer has, and
nothing has written them since; the reader that served them is gone too. A price
book is now read by `index_catalog` into pageIndex and priceBookEntries.
"""
from __future__ import annotations

VERSION = 8
DESCRIPTION = "drop the retired catalogPages and multiplierPages collections"

RETIRED = ("catalogPages", "multiplierPages")


async def apply(db) -> None:
    present = set(await db.list_collection_names())
    for name in RETIRED:
        if name in present:
            await db[name].drop()
