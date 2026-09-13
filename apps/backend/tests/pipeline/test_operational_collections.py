"""The four collections that carry FR-12, FR-13, FR-16 and Phase 5.

Each of those requirements audited as ABSENT, and the reason was the same in
every case: there was no collection to put the data in. `VENDOR_RFQ` was a
`CostSource` value with no way to set it; `feedbackEvents` was an unfilled
`"estimatorCorrections": None`; Phase 5's questions lived as free text in a
general-purpose `calls` log.

These tests hold the shapes and the state machines. Wiring them to routes is the
next step; a collection with the right shape is what stops that step inventing
its own.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cbc.modules.extraction.domain import feedback_and_takeoffs as extraction_op
from cbc.modules.quoting.domain import rfqs_and_rfis as op


def now() -> datetime:
    return datetime.now(timezone.utc)


# ── FR-16: the vendor RFQ loop ──────────────────────────────────────────────


def test_an_rfq_starts_as_a_draft_that_blocks_nothing() -> None:
    rfq = op.VendorRfq(rfqNumber="RFQ-1", bidRequestId="b1", triggerReason="customSize")
    assert rfq.status == "draft"
    assert rfq.blocksBid is False
    assert rfq.quotedPrices == []


def test_the_rfq_path_runs_request_to_applied() -> None:
    """§3.28: draft -> requested -> awaiting -> received -> applied."""
    path = ["draft", "requested", "awaiting", "received", "applied"]
    for current, target in zip(path, path[1:]):
        op.check_transition(op.RFQ_TRANSITIONS, current, target, label="rfq")


def test_an_rfq_can_expire_while_waiting() -> None:
    """A quote has a validUntil; Matrix 6.6 notes an RFQ can hold up a bid."""
    op.check_transition(op.RFQ_TRANSITIONS, "awaiting", "expired", label="rfq")
    op.check_transition(op.RFQ_TRANSITIONS, "received", "expired", label="rfq")


def test_an_applied_rfq_is_terminal() -> None:
    assert op.next_states(op.RFQ_TRANSITIONS, "applied") == ()
    with pytest.raises(ValueError, match="applied -> cancelled"):
        op.check_transition(op.RFQ_TRANSITIONS, "applied", "cancelled", label="rfq")


def test_an_rfq_cannot_skip_straight_to_a_price() -> None:
    with pytest.raises(ValueError, match="draft -> received"):
        op.check_transition(op.RFQ_TRANSITIONS, "draft", "received", label="rfq")


def test_a_returned_price_carries_its_own_validity() -> None:
    """NR-2's "price may be out of date" needs a date to be out of."""
    price = op.RfqPrice(amount=1240.0, validUntil=now(), leadTimeDays=42)
    assert price.currency == "USD"
    assert price.validUntil is not None


# ── Phase 5: RFIs ───────────────────────────────────────────────────────────


def test_an_rfi_records_what_kind_of_gap_it_is() -> None:
    """The categories are the flags the take-off already raises (Matrix 7.3, 6.4)."""
    rfi = op.Rfi(
        bidRequestId="b1", rfiNumber="RFI-1", subject="Door 01 rating",
        question="Schedule shows no rating on a rated wall - 90 minute?",
        category="missingRating", raisedAt=now(), blocksFinalization=True,
    )
    assert rfi.status == "open"
    assert rfi.blocksFinalization is True


def test_a_substitution_approval_is_an_rfi_category() -> None:
    """Matrix 6.4: the GC approves a direct equal. Somewhere has to record that."""
    assert "substitutionApproval" in op.RfiCategory.__args__


def test_an_rfi_must_be_sent_before_it_can_be_answered() -> None:
    with pytest.raises(ValueError, match="open -> answered"):
        op.check_transition(op.RFI_TRANSITIONS, "open", "answered", label="rfi")
    op.check_transition(op.RFI_TRANSITIONS, "open", "sent", label="rfi")
    op.check_transition(op.RFI_TRANSITIONS, "sent", "answered", label="rfi")


# ── FR-13: estimator corrections ────────────────────────────────────────────


def test_a_correction_records_what_the_copilot_claimed() -> None:
    """The field that makes confidence calibratable rather than asserted."""
    event = extraction_op.FeedbackEvent(
        bidRequestId="b1", eventType="matchCorrected", field="partNumber",
        proposedValue={"part": "1191"}, correctedValue={"part": "1279"},
        matchConfidenceAtTime=0.82, occurredAt=now(),
    )
    assert event.matchConfidenceAtTime == 0.82
    assert event.appliedToLearning is False, "nothing has consumed it yet"


def test_every_review_action_has_an_event_type() -> None:
    """FR-9 lets an estimator accept, edit, delete or add. FR-13 records each."""
    for kind in ("matchRejected", "matchCorrected", "lineAdded", "lineDeleted",
                 "extractionCorrected", "costOverridden", "marginOverridden",
                 "substitutionMade"):
        assert kind in extraction_op.FeedbackType.__args__


def test_an_extraction_correction_points_at_an_opening_not_a_line() -> None:
    event = extraction_op.FeedbackEvent(
        bidRequestId="b1", openingId="o1", eventType="extractionCorrected",
        field="fireRating", occurredAt=now(),
    )
    assert event.openingId == "o1"
    assert event.estimateLineId is None


# ── FR-12: the FRP take-off ─────────────────────────────────────────────────


def test_a_takeoff_holds_geometry_and_admits_the_conversion_is_owed() -> None:
    """Open Item 5: CBC has not provided the conversion constants."""
    takeoff = extraction_op.Takeoff(
        bidRequestId="b1", perimeterLf=184.5, insideCorners=6, outsideCorners=2,
        wallHeightFt=8.0,
    )
    assert takeoff.status == "pendingConstants"
    assert takeoff.constantsUsed is None
    assert takeoff.quantities is None, "quantities without constants would be invented"


def test_a_converted_takeoff_says_which_constants_it_used() -> None:
    """When the constants arrive, the take-off records the ones it applied - so a
    later change to them does not silently restate an old quantity."""
    takeoff = extraction_op.Takeoff(
        bidRequestId="b1", perimeterLf=184.5, status="converted",
        constantsUsed={"panelWidthFt": 4.0, "wastePct": 0.10},
        quantities={"panels": 51},
    )
    assert takeoff.constantsUsed["panelWidthFt"] == 4.0
    assert takeoff.quantities["panels"] == 51
