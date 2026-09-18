"""What an estimator has confirmed a specification means (FR-13).

Catalog owns `matchLearning` because a learned answer *is* a catalog fact: this
specification, on this account, means this part. What it is learned *from* -
`feedbackEvents` - belongs to extraction, so extraction drains its own queue and
calls in here. The arrow runs extraction -> catalog, the way every other one
between these two already does.

What this builds is deliberately not a model. It is a lookup table, which is what
an estimator's own memory is: auditable by name and date, useful on the second
bid, and needing no training run to become either.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.catalog.domain import partquery
from cbc.modules.catalog.infrastructure.collections import match_learning, products
from cbc.shared.mongo import oid
from cbc.shared.persistence import envelope


async def resolve_item(item_id: Any = None, part: Any = None) -> dict[str, Any] | None:
    """The catalog row a correction points at: by id when it has one, else by part."""
    if item_id is not None:
        try:
            row = await products().find_one({"_id": oid(str(item_id))})
        except (ValueError, TypeError):
            row = None
        if row:
            return row
    text = str(part or "").strip()
    if not text:
        return None
    for candidate in partquery.normalize(text):
        row = await products().find_one(partquery.identity_filter(candidate))
        if row:
            return row
    return None


async def confirm(
    *,
    org_id: Any,
    spec: Any,
    item: dict[str, Any],
    rejected: bool = False,
    event_id: Any = None,
    reason: str | None = None,
    at: Any = None,
    by: Any = None,
) -> bool:
    """Record that an estimator chose (or rejected) `item` for `spec`.

    Returns False when the specification normalises to nothing - there is no key
    to learn against, and a blank one would collide with every other blank.
    """
    key = partquery.spec_key(spec)
    if not key or not item:
        return False

    now = envelope.now()
    changes: dict[str, Any] = {
        "specSample": str(spec),
        "catalogItemId": item["_id"],
        "part": item.get("part"),
        "manufacturer": item.get("manufacturer"),
        "division": item.get("division"),
        "updatedAt": now,
    }
    if not rejected:
        changes["lastConfirmedAt"] = at or now
        changes["lastConfirmedBy"] = by

    counter = "rejectCount" if rejected else "confirmCount"
    # The counter being incremented must not also appear in $setOnInsert - Mongo
    # rejects the same field under two update operators - so only the other one
    # is seeded.
    other = "confirmCount" if rejected else "rejectCount"
    add_to_set: dict[str, Any] = {}
    if event_id is not None:
        add_to_set["sourceEventIds"] = event_id
    if str(reason or "").strip():
        add_to_set["reasons"] = str(reason)

    update: dict[str, Any] = {
        "$set": changes,
        "$inc": {counter: 1},
        "$setOnInsert": {
            "orgId": org_id,
            "specKey": key,
            other: 0,
            "createdAt": now,
        },
    }
    if add_to_set:
        update["$addToSet"] = add_to_set

    await match_learning().update_one({"orgId": org_id, "specKey": key}, update, upsert=True)
    return True


async def recall(spec: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """Exact recall for a specification, for the API and the tests.

    The matcher's own recall is the sync one in `api/pageindex/reader`, which the
    MCP server reaches with the read-only credential; this is the async side for
    anything running inside the app.
    """
    key = partquery.spec_key(spec)
    if not key:
        return []
    return await match_learning().find({"specKey": key}).limit(limit).to_list(limit)


async def total() -> int:
    """How many specifications CBC has been taught."""
    return int(await match_learning().count_documents({}))
