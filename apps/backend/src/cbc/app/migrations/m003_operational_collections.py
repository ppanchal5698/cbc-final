"""Create the four operational collections and their indexes.

`takeoffs`, `vendorRfqs`, `rfis` and `feedbackEvents` are FR-12, FR-16, Phase 5
and FR-13. None of them existed, which is why each of those requirements audited
as ABSENT rather than partial - there was no phase that owned them and nowhere to
put the data if there had been.

Mongo creates a collection on first write, so strictly this migration is about
the *indexes*: an empty collection with the right indexes is a promise about how
it will be read, and the specification's index list (§3.28, §3.29, §3.31) encodes
the questions each one exists to answer - the RFQ chase list ordered by due date,
what is blocking delivery, correction-type frequency over time.

Every index leads with `orgId`, per §4.1.
"""
from __future__ import annotations

import logging

from cbc.shared.persistence import names

VERSION = 3
DESCRIPTION = "create takeoffs, vendorRfqs, rfis and feedbackEvents with their indexes"

log = logging.getLogger("cbc.migrations")

CREATED = (names.TAKEOFFS, names.VENDOR_RFQS, names.RFIS, names.FEEDBACK_EVENTS)


async def apply(db) -> None:
    existing = set(await db.list_collection_names())
    for collection in CREATED:
        if collection not in existing:
            await db.create_collection(collection)
            log.info("  created %s", collection)

    # §3.28 - the third cost path, and the two questions an estimator asks of it:
    # what am I waiting on, and what is holding up the bid?
    rfqs = db[names.VENDOR_RFQS]
    await rfqs.create_index([("orgId", 1), ("rfqNumber", 1)], name="rfq_number", unique=True)
    await rfqs.create_index(
        [("orgId", 1), ("bidRequestId", 1), ("status", 1)], name="rfq_on_bid"
    )
    await rfqs.create_index(
        [("orgId", 1), ("status", 1), ("dueBy", 1)],
        name="rfq_chase_list",
        partialFilterExpression={"status": {"$in": ["requested", "awaiting"]}},
    )
    await rfqs.create_index(
        [("orgId", 1), ("blocksBid", 1), ("status", 1)],
        name="rfq_blocking",
        partialFilterExpression={"blocksBid": True},
    )
    await rfqs.create_index(
        [("orgId", 1), ("vendorId", 1), ("requestedAt", -1)], name="rfq_by_vendor"
    )

    # §3.29 - Phase 5. `blocksFinalization` is the "before finalizing" in the
    # process flow: an unanswered question that must not be quietly passed over.
    rfis = db[names.RFIS]
    await rfis.create_index([("orgId", 1), ("bidRequestId", 1), ("status", 1)], name="rfi_on_bid")
    await rfis.create_index(
        [("orgId", 1), ("blocksFinalization", 1), ("status", 1)],
        name="rfi_blocking",
        partialFilterExpression={"blocksFinalization": True},
    )

    # §3.31 - FR-13. The first index is the core improvement metric: which kind
    # of correction an estimator makes, and whether it is happening less often.
    feedback = db[names.FEEDBACK_EVENTS]
    await feedback.create_index(
        [("orgId", 1), ("eventType", 1), ("occurredAt", -1)], name="feedback_by_type"
    )
    await feedback.create_index(
        [("orgId", 1), ("appliedToLearning", 1)],
        name="feedback_unconsumed",
        partialFilterExpression={"appliedToLearning": False},
    )
    await feedback.create_index([("orgId", 1), ("bidRequestId", 1)], name="feedback_on_bid")

    # §3.24 - FRP geometry, one take-off per bid per type.
    takeoffs = db[names.TAKEOFFS]
    await takeoffs.create_index(
        [("orgId", 1), ("bidRequestId", 1), ("takeoffType", 1)], name="takeoff_on_bid"
    )
