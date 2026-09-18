"""Record what an estimator corrected, so matching can be measured.

FR-13: *capture estimator corrections as structured feedback to improve future
matching.* The 14 Jul session framed it as the direction of travel - "keep
feeding it information and grow it".

Nothing captured any. Edits landed in `auditLog`, which records that a field
changed and is the wrong shape for this question: an audit entry says
`{before, after}` for a document, while improving a matcher needs to know what
the copilot *proposed*, what the estimator *chose instead*, and how confident the
copilot was when it was wrong. `runmetrics.py` even carried an unfilled
`"estimatorCorrections": None` where this was meant to go.

Writing a feedback event must never be able to fail the edit that produced it.
An estimator correcting a fire rating at 4pm on a bid due at 5 does not care that
the learning pipeline had a bad day, so every failure here is logged and
swallowed - the correction itself is already committed and audited.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from cbc.modules.extraction.infrastructure.collections import feedback_events

log = logging.getLogger("cbc.services.feedback")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def record(
    *,
    bid_request_id: Any,
    event_type: str,
    actor: Any = None,
    estimate_line_id: Any = None,
    opening_id: Any = None,
    field: str | None = None,
    proposed: Any = None,
    corrected: Any = None,
    confidence: float | None = None,
    reason: str | None = None,
    proposed_catalog_item_id: Any = None,
    corrected_catalog_item_id: Any = None,
    spec: Any = None,
) -> None:
    """One correction, appended. Never raises."""
    try:
        await feedback_events().insert_one({
            "bidRequestId": bid_request_id,
            "estimateLineId": estimate_line_id,
            "openingId": opening_id,
            "eventType": event_type,
            "field": field,
            # Typed as objects in §3.31 so any shape fits - a part number, a
            # rating, a whole line.
            "proposedValue": {"value": proposed} if proposed is not None else None,
            "correctedValue": {"value": corrected} if corrected is not None else None,
            # §3.31 defined both pointers from the start and nothing wrote them,
            # so a correction recorded that a part number changed without saying
            # which catalog row the estimator actually meant. A learning pass
            # cannot act on a string; these are what make the event usable.
            "proposedCatalogItemId": proposed_catalog_item_id,
            "correctedCatalogItemId": corrected_catalog_item_id,
            # The specification this correction was about, kept verbatim so the
            # learning pass can key on it without re-reading the line.
            "specifiedItem": spec,
            "matchConfidenceAtTime": confidence,
            "reason": reason,
            "userId": actor,
            "occurredAt": _now(),
            "appliedToLearning": False,
        })
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        log.warning("feedback not recorded (%s): %s", event_type, exc)


# Which edit means which kind of correction. `field` -> §3.31 `eventType`.
FIELD_EVENTS = {
    "cost": "costOverridden",
    "margin": "marginOverridden",
    "costSource": "costOverridden",
    "fireRating": "extractionCorrected",
    "handing": "extractionCorrected",
    "finish": "extractionCorrected",
    "size": "extractionCorrected",
    "hwSet": "matchCorrected",
    "part": "matchCorrected",
    "partNumber": "matchCorrected",
    "catalogItemId": "matchCorrected",
    "manufacturer": "matchCorrected",
    "substitution": "substitutionMade",
}

# The corrections that teach the matcher something. A margin override is a
# commercial decision about a correct match, not a different answer to "which
# part is this", so it is captured but never learned from.
MATCH_EVENTS = frozenset({"matchCorrected", "matchRejected", "substitutionMade"})


async def unapplied(
    event_types: Iterable[str] | None = None, *, limit: int = 500
) -> list[dict[str, Any]]:
    """The unconsumed-feedback queue, oldest first.

    §3.31 defined `appliedToLearning` and a partial index over the `false` half
    from the start, and nothing ever read either - the system test says as much:
    *"nothing has consumed it yet"*. This is the read that queue was built for.

    Oldest first so a replayed drain applies corrections in the order the
    estimator made them, and the last word is the most recent one.
    """
    query: dict[str, Any] = {"appliedToLearning": False}
    if event_types:
        query["eventType"] = {"$in": sorted(set(event_types))}
    return await feedback_events().find(query).sort("occurredAt", 1).to_list(limit)


async def mark_applied(event_ids: Iterable[Any]) -> int:
    """Flip `appliedToLearning`, so a second drain cannot count the same lesson twice."""
    ids = [eid for eid in event_ids if eid is not None]
    if not ids:
        return 0
    result = await feedback_events().update_many(
        {"_id": {"$in": ids}}, {"$set": {"appliedToLearning": True}}
    )
    return result.modified_count


def _unwrap(value: Any) -> Any:
    """`proposedValue` / `correctedValue` are `{value: ...}` per §3.31."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


async def apply_to_learning(*, limit: int = 500) -> dict[str, Any]:
    """Drain the queue into what the matcher knows. Idempotent per event.

    The queue is ours; `matchLearning` is catalog's, so the write goes through
    `catalog.api.learning` rather than naming another module's collection.

    Every event read is flipped, including the ones that taught nothing: an event
    that named no catalog row will never name one however often it is re-read,
    and leaving it unapplied means every later drain walks past it again.
    """
    from cbc.modules.catalog.api import learning
    from cbc.shared.persistence import repos

    events = await unapplied(MATCH_EVENTS, limit=limit)
    if not events:
        return {"read": 0, "learned": 0, "rejected": 0, "skipped": 0, "marked": 0}

    org_id = await repos.org_id_for()
    learned = rejected = skipped = 0
    drained: list[Any] = []

    for event in events:
        drained.append(event.get("_id"))
        is_rejection = event.get("eventType") == "matchRejected"
        # A rejection teaches about the part that was *proposed*; a correction
        # teaches about the one the estimator chose instead.
        side = "proposed" if is_rejection else "corrected"
        item = await learning.resolve_item(
            event.get(f"{side}CatalogItemId"), _unwrap(event.get(f"{side}Value"))
        )
        if item is None:
            skipped += 1
            continue
        applied = await learning.confirm(
            org_id=org_id,
            spec=event.get("specifiedItem") or _unwrap(event.get("proposedValue")),
            item=item,
            rejected=is_rejection,
            event_id=event.get("_id"),
            reason=event.get("reason"),
            at=event.get("occurredAt"),
            by=event.get("userId"),
        )
        if not applied:
            skipped += 1
        elif is_rejection:
            rejected += 1
        else:
            learned += 1

    marked = await mark_applied(drained)
    log.info(
        "match feedback drained: %s read, %s learned, %s rejected, %s skipped",
        len(events),
        learned,
        rejected,
        skipped,
    )
    return {
        "read": len(events),
        "learned": learned,
        "rejected": rejected,
        "skipped": skipped,
        "marked": marked,
    }


async def record_edits(
    *,
    bid_request_id: Any,
    changes: dict[str, Any],
    before: dict[str, Any],
    actor: Any,
    estimate_line_id: Any = None,
    opening_id: Any = None,
    reason: str | None = None,
) -> None:
    """Fan one edit out into an event per corrected field.

    A single PATCH that fixes a rating *and* a cost is two different lessons, and
    collapsing them into one row would make the improvement metric meaningless.
    """
    # What the line was specified as, which is the question a match answers and
    # the key the learning pass recalls on. Taken from `before`, so it is the
    # specification rather than whatever the estimator just typed.
    spec = (
        before.get("specified")
        or before.get("specifiedItem")
        or before.get("description")
        or before.get("part")
    )
    for field, value in changes.items():
        event_type = FIELD_EVENTS.get(field)
        if event_type is None:
            continue  # a rename or a note is not a correction
        await record(
            bid_request_id=bid_request_id,
            event_type=event_type,
            actor=actor,
            estimate_line_id=estimate_line_id,
            opening_id=opening_id,
            field=field,
            proposed=before.get(field),
            corrected=value,
            confidence=before.get("confidence"),
            reason=reason,
            proposed_catalog_item_id=before.get("catalogItemId"),
            corrected_catalog_item_id=(
                value if field == "catalogItemId" else changes.get("catalogItemId")
            ),
            spec=spec,
        )
