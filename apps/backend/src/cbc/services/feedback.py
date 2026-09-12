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
from datetime import datetime, timezone
from typing import Any

from cbc.db import db

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
) -> None:
    """One correction, appended. Never raises."""
    try:
        await db.feedback_events.insert_one({
            "bidRequestId": bid_request_id,
            "estimateLineId": estimate_line_id,
            "openingId": opening_id,
            "eventType": event_type,
            "field": field,
            # Typed as objects in §3.31 so any shape fits - a part number, a
            # rating, a whole line.
            "proposedValue": {"value": proposed} if proposed is not None else None,
            "correctedValue": {"value": corrected} if corrected is not None else None,
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
        )
