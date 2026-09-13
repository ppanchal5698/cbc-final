"""Create the organization, and give every existing document the §4.2 envelope.

`grep orgId` over the repository returned nothing. The specification (§4.1) makes
it the first field of every document and the leading key of every compound index,
"so the tenant filter is always index-covered and a missing filter degrades to a
scan that will be noticed in profiling rather than silently returning another
tenant's data". You cannot inject a tenant id that does not exist, so this
migration mints one and stamps what is already stored.

CBC is the only tenant today, and its identity is not invented here - Matrix 2.0
gives it: Hamilton Parker's national-accounts division, 1865 Leonard Ave,
Columbus OH. Other Hamilton Parker divisions are out of scope but extensible
later, which is exactly why the field exists now rather than when a second
division appears.

Idempotent: the organization is upserted on a stable key, and the backfill only
touches documents that lack `orgId`, so a re-run matches nothing.
"""
from __future__ import annotations

import logging

from cbc.shared.persistence import envelope, names

VERSION = 2
DESCRIPTION = "create the CBC organization and backfill orgId/schemaVersion onto every document"

log = logging.getLogger("cbc.migrations")

# Matrix 2.0. `slug` is the stable key, so a re-run finds the same row rather
# than minting a second organization.
CBC = {
    "slug": "cbc",
    "name": "Construction Building Components",
    "parent": "The Hamilton Parker Company",
    "description": "Hamilton Parker's national-accounts division",
    "address": {
        "street": "1865 Leonard Ave",
        "city": "Columbus",
        "state": "OH",
        "country": "US",
    },
}

# Everything that holds tenant data. Deliberately excluded: `schemaMigrations`
# (this ledger), `settings` and `counters` (installation-wide, keyed by name, one
# row per concern), and `authAttempts` / `oauthSessions` (TTL rows that expire
# before a tenant question could be asked of them).
TENANT_COLLECTIONS = (
    names.USERS,
    names.BID_REQUESTS,
    names.DOCUMENTS,
    names.OPENINGS,
    names.ESTIMATE_VERSIONS,
    names.ESTIMATE_LINES,
    names.CATALOG_ITEMS,
    names.PRICE_BOOKS,
    names.PROPOSALS,
    names.AUDIT_LOGS,
    names.QUOTES,
    names.CALLS,
    names.JOBS,
    names.RUN_METRICS,
    names.FAILED_EXTRACTIONS,
    names.REFERENCE_DATA,
)


async def apply(db) -> None:
    await db[names.ORGANIZATIONS].update_one(
        {"slug": CBC["slug"]},
        {
            "$set": {**CBC, "updatedAt": envelope.now()},
            "$setOnInsert": {
                "schemaVersion": envelope.SCHEMA_VERSION,
                "createdAt": envelope.now(),
                "createdBy": None,
                "updatedBy": None,
            },
        },
        upsert=True,
    )
    org = await db[names.ORGANIZATIONS].find_one({"slug": CBC["slug"]}, {"_id": 1})
    org_id = org["_id"]

    for collection in TENANT_COLLECTIONS:
        result = await db[collection].update_many(
            {"orgId": {"$exists": False}},
            {
                "$set": {
                    "orgId": org_id,
                    "schemaVersion": envelope.SCHEMA_VERSION,
                }
            },
        )
        if result.modified_count:
            log.info("  %s: %d document(s) stamped", collection, result.modified_count)

    # The tenant filter has to be index-covered or §4.1's argument does not hold.
    for collection in TENANT_COLLECTIONS:
        await db[collection].create_index([("orgId", 1)], name="org")
