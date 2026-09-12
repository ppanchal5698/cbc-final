"""Rename the operational collections to the names the specification gives them.

`docs/collections.mongodb.md` is design-complete and derived from the requirements
workbook. The database used different words for the same things, so a reader
holding the specification could not find a bid, an opening or a priced line:

    projects   -> bidRequests      §3.21
    lineItems  -> openings         §3.23
    quoteLines -> estimateLines    §3.27
    products   -> catalogItems     §3.9
    auditLog   -> auditLogs        §3.32

`renameCollection` is atomic and keeps indexes, so this is a metadata operation
rather than a copy - a 300-openings bid set is renamed in milliseconds, not
rewritten document by document.

Idempotent in the three ways it needs to be: a source that is already gone is
skipped, a target that already holds data is left alone and reported, and a run
where neither exists does nothing at all. That matters because six API containers
each run startup, and because a migration that raises is retried on the next boot.
"""
from __future__ import annotations

import logging

from cbc.persistence.names import RENAMED_IN_M001

VERSION = 1
DESCRIPTION = "rename projects/lineItems/quoteLines/products/auditLog to the specification names"

log = logging.getLogger("cbc.migrations")


async def apply(db) -> None:
    existing = set(await db.list_collection_names())

    for old, new in RENAMED_IN_M001.items():
        if old not in existing:
            # Already renamed on a previous run, or a fresh database that never
            # had the old name. Either way there is nothing to move.
            continue
        if new in existing:
            # Both names present. Renaming would destroy `new`, so refuse and
            # say so rather than picking one - a half-migrated database is a
            # question for a person.
            raise RuntimeError(
                f"cannot rename {old!r} to {new!r}: both collections exist. "
                f"Merge or drop one by hand, then re-run the migration."
            )
        await db[old].rename(new)
        log.info("  %s -> %s", old, new)
