"""Create the reference spine collections that `referenceData` blobs stand in for.

S4: organizations already exists (m002). customers, vendors, productTypes,
brandPrograms, and marginRules get empty collections + indexes so the API can
write them without inventing a parallel schema. Live family blobs in
`referenceData` remain the read path until a follow-on data move.
"""
from __future__ import annotations

import logging

VERSION = 5
DESCRIPTION = "create reference spine collections (customers, vendors, productTypes, …)"

log = logging.getLogger("cbc.migrations")

SPINE = (
    "customers",
    "vendors",
    "productTypes",
    "brandPrograms",
    "marginRules",
    "taxRules",
    "adders",
    "vendorTiers",
)


async def apply(db) -> None:
    for name in SPINE:
        coll = db[name]
        await coll.create_index([("orgId", 1)], name="org")
        await coll.create_index([("orgId", 1), ("active", 1)], name="org_active")
        log.info("spine collection ready: %s", name)

    await db["customers"].create_index(
        [("orgId", 1), ("name", 1)], name="customer_name"
    )
    await db["vendors"].create_index(
        [("orgId", 1), ("name", 1)], name="vendor_name", unique=True
    )
    await db["productTypes"].create_index(
        [("orgId", 1), ("key", 1)], name="product_type_key", unique=True
    )
