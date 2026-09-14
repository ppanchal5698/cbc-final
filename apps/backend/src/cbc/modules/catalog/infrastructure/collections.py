"""The collections catalog owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.catalog.api`.
"""
from __future__ import annotations

import asyncio
import logging

from pymongo import ASCENDING, TEXT
from pymongo.errors import DuplicateKeyError, OperationFailure

from cbc.shared.persistence import names
from cbc.shared.mongo import INDEX_BUILD_ABORTED, create_index_resilient, database, replace_index

log = logging.getLogger("cbc.api.db")  # the name these index messages have always logged under


def products():
    return database()[names.CATALOG_ITEMS]


def price_books():
    return database()[names.PRICE_BOOKS]


async def _ensure_part_lookup_index() -> None:
    """Ensure non-unique `part_lookup`; migrate away from auto-named `part_1`.

    Older startups created `[("part", ASCENDING)]` without a name, so Mongo
    called it `part_1` (same as the legacy unique index). Creating `part_lookup`
    on the same key then fails with IndexOptionsConflict. Drop any leftover
    `part_1` — unique or not — then create the named lookup index.
    """
    try:
        info = await products().index_information()
    except OperationFailure:
        info = {}
    if "part_lookup" in info:
        return
    if "part_1" in info:
        try:
            await products().drop_index("part_1")
            log.info("dropped products.part_1 (migrating to part_lookup)")
        except OperationFailure as exc:
            if exc.code != INDEX_BUILD_ABORTED:
                log.debug("products.part_1 drop skipped: %s", exc)
            await asyncio.sleep(0.3)
    await create_index_resilient(
        products(), [("part", ASCENDING)], name="part_lookup"
    )


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, like every module's."""
    # Hager's 1234 and Rockwood's 1234 are different parts. A unique index on
    # `part` alone made the price-book ingest upsert one over the other, so the
    # second vendor's sheet silently replaced the first vendor's costs.
    #
    # The legacy unique index was auto-named `part_1`. An unnamed non-unique
    # `[("part", ASCENDING)]` gets the same name — concurrent drop/create races
    # abort index builds, and a leftover non-unique `part_1` blocks creating
    # `part_lookup`. Migrate explicitly via `_ensure_part_lookup_index`.
    await _ensure_part_lookup_index()
    await create_index_resilient(products(), [("division", ASCENDING)])
    try:
        await replace_index(
            products(),
            "product_identity",
            [("manufacturer", ASCENDING), ("part", ASCENDING)],
            unique=True,
        )
    except DuplicateKeyError:
        log.error(
            "products already holds two rows with the same manufacturer and part, so "
            "the unique index could not be built. Run scripts/dedupe_products.py, "
            "then restart. Ingest is keyed on (manufacturer, part) either way."
        )
    # A collection holds one text index; an earlier app's (sku, description) one
    # made a plain create_index of this refuse to start. The helper swaps it over.
    await create_index_resilient(
        products(),
        [("part", TEXT), ("description", TEXT), ("manufacturer", TEXT)],
        name="product_search",
    )
    await price_books().create_index([("vendor", ASCENDING), ("program", ASCENDING)])
