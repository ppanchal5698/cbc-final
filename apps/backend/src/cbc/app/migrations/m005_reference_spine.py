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
    # A database that already held a spine collection from an earlier app carries
    # the same keys under Mongo's auto-generated name (brandPrograms'
    # orgId_1_active_1). A plain create_index refuses that with IndexOptionsConflict
    # and stops every API start; create_index_resilient swaps the name over.
    from cbc.shared.mongo import create_index_resilient

    for name in SPINE:
        coll = db[name]
        await create_index_resilient(coll, [("orgId", 1)], name="org")
        await create_index_resilient(coll, [("orgId", 1), ("active", 1)], name="org_active")
        log.info("spine collection ready: %s", name)

    await create_index_resilient(db["customers"], [("orgId", 1), ("name", 1)], name="customer_name")
    await create_index_resilient(db["vendors"], [("orgId", 1), ("name", 1)], name="vendor_name", unique=True)
    await create_index_resilient(db["productTypes"], [("orgId", 1), ("key", 1)], name="product_type_key", unique=True)
