"""The fields every stored document carries, and the rules about them.

`docs/collections.mongodb.md` §4.2-§4.6 specifies four cross-cutting mechanisms.
None of them existed: `grep orgId` over the whole repo returned nothing, and so
did `schemaVersion`, `isDeleted` and `effectiveFrom`.

    §4.2  audit envelope   orgId, schemaVersion, createdAt/By, updatedAt/By
    §4.3  soft delete      five collections, and only those five
    §4.4  schema version   documents written at N, readers handle N and N-1
    §4.6  effective dating nine reference collections, versioned not overwritten

The last one is the one with teeth. `reference_store.replace_one(...)` destroys
the previous document wholesale, so editing a margin band or a tax rate erases the
answer to "what was the rate when we quoted this?" - which NFR-3 requires and
which §4.6 exists to protect. Price changes arrive as dated memos with a
protection window (Matrix 6.3); an in-place update cannot represent that.

Everything here is a pure function over dictionaries. Applying it to real writes
is the repositories' job.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.persistence import names

# §4.4. Documents are written at this version; a reader handles this and the one
# below it while a backfill runs, rather than stopping the world to migrate.
SCHEMA_VERSION = 1

# §4.3. Exactly these five, and the specification is explicit that it is only
# these: the rest are append-only records, children hidden by a soft-deleted
# parent, or reference data deactivated with `active: false` instead.
SOFT_DELETED = frozenset({
    names.ESTIMATES,
    names.ESTIMATE_VERSIONS,
    names.BID_REQUESTS,
    names.PRICE_BOOKS,
    "vendors",
})

# §4.6. Reference data that changes over time is versioned by effective date and
# never updated in place.
EFFECTIVE_DATED = frozenset({
    names.PRICE_BOOKS,
    names.PRICE_BOOK_ENTRIES,
    "vendorTiers",
    "marginRules",
    "adders",
    "lightKitRates",
    "taxRules",
    "commercialTermsTemplates",
    "frpConstants",
})


def now() -> datetime:
    """One clock, so a document's timestamps agree with each other."""
    return datetime.now(timezone.utc)


def stamp_new(
    document: dict[str, Any],
    *,
    org_id: Any,
    actor_id: Any = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """The §4.2 envelope for an insert. Returns a new dict; does not mutate.

    `actor_id` is None for system and import writes, which the specification
    permits and which is why the field is nullable rather than required.
    """
    moment = at or now()
    return {
        **document,
        "orgId": org_id,
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": moment,
        "updatedAt": moment,
        "createdBy": actor_id,
        "updatedBy": actor_id,
    }


def stamp_update(
    changes: dict[str, Any], *, actor_id: Any = None, at: datetime | None = None
) -> dict[str, Any]:
    """The envelope fields an update must also set. `createdAt` is never touched."""
    return {**changes, "updatedAt": at or now(), "updatedBy": actor_id}


def soft_delete(*, actor_id: Any = None, at: datetime | None = None) -> dict[str, Any]:
    """§4.3 delete fields.

    `retentionPolicy` is deliberately absent rather than guessed. The workbook
    gives no retention rule anywhere, and the specification is explicit that this
    is a business decision not to be manufactured - the field exists on the
    document so that setting a policy later is a data change, not a migration.
    """
    return {"isDeleted": True, "deletedAt": at or now(), "deletedBy": actor_id}


def alive() -> dict[str, Any]:
    """The filter fragment every query on a soft-deleted collection needs.

    `{"isDeleted": {"$ne": True}}` rather than `{"isDeleted": False}`, so a
    document written before the field existed is still visible. A backfill makes
    them equivalent; until then, only the first one is correct.
    """
    return {"isDeleted": {"$ne": True}}


def effective(
    document: dict[str, Any], *, frm: datetime, to: datetime | None = None
) -> dict[str, Any]:
    """§4.6 effective dating. `effectiveTo=None` means currently in force."""
    return {**document, "effectiveFrom": frm, "effectiveTo": to}


def in_force_at(when: datetime | None = None) -> dict[str, Any]:
    """Filter for the record that was in force at a moment - now by default.

    This is the query NFR-3 turns on: what was the multiplier tier, the list
    price, the margin band when this line was quoted?
    """
    moment = when or now()
    return {
        "effectiveFrom": {"$lte": moment},
        "$or": [{"effectiveTo": None}, {"effectiveTo": {"$gt": moment}}],
    }


def supersede(*, at: datetime | None = None) -> dict[str, Any]:
    """Close the current record instead of overwriting it.

    The replacement is a new document with `effectiveFrom` set to the same
    moment, so the pair reads as a history rather than a mutation.
    """
    return {"effectiveTo": at or now()}
