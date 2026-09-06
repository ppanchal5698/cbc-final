"""A proposal cannot exist without a human having approved it.

`collections.mongodb.md` §3.30 marks `approvedBy` required, with the note that
"a proposal cannot exist without a human approval" - it is the specification's
one schema-level enforcement of NFR-1, the rule the whole product turns on:
*the copilot drafts, sources, and calculates; it does not send.*

`approvedBy` did not exist. The nearest thing was a `signoff[]` entry pushed by
the hand-off handler itself, on an `upsert=True` write - so the act of handing a
proposal off would create the proposal document, with no approval step preceding
it and nothing recording who took responsibility.

Two frozen snapshots are the other half of §3.30. `termsSnapshot` and
`totalsSnapshot` are read live today - `VALIDITY_DAYS` is a module constant and
totals are recomputed on every render - so a proposal already handed to a
customer renders differently after any later line edit.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cbc.persistence import proposals


def test_approval_needs_a_named_person() -> None:
    """NFR-1, at the only layer that can actually enforce it."""
    with pytest.raises(proposals.ApprovalRequired, match="human"):
        proposals.approve(approved_by=None, totals={}, terms={})


def test_an_approved_proposal_records_who_and_when() -> None:
    at = datetime(2026, 9, 6, tzinfo=timezone.utc)
    record = proposals.approve(
        approved_by="kevin@cbc.com",
        totals={"grandTotal": 12345.67, "currency": "USD"},
        terms={"validityDays": 30, "poRequired": True},
        at=at,
    )
    assert record["approvedBy"] == "kevin@cbc.com"
    assert record["approvedAt"] == at
    assert record["status"] == "generated"


def test_the_totals_are_frozen_not_referenced() -> None:
    """§3.30: totalsSnapshot, frozen. Recomputing on read is the defect."""
    totals = {"grandTotal": 12345.67, "currency": "USD"}
    record = proposals.approve(approved_by="kevin@cbc.com", totals=totals, terms={})

    totals["grandTotal"] = 999.99  # a later line edit moves the live figure
    assert record["totalsSnapshot"]["grandTotal"] == 12345.67


def test_the_terms_are_frozen_too() -> None:
    """A customer's copy must not change when the template does."""
    terms = {"validityDays": 30, "poRequired": True, "supplyOnly": True}
    record = proposals.approve(approved_by="kevin@cbc.com", totals={}, terms=terms)

    terms["validityDays"] = 7
    assert record["termsSnapshot"]["validityDays"] == 30


def test_a_hand_off_cannot_manufacture_an_approval() -> None:
    """The `upsert=True` defect, stated as a rule."""
    with pytest.raises(proposals.ApprovalRequired):
        proposals.guard_approved({})
    with pytest.raises(proposals.ApprovalRequired):
        proposals.guard_approved({"signoff": [{"role": "estimator", "by": "kevin"}]})


def test_an_approved_proposal_may_be_handed_off() -> None:
    approved = proposals.approve(approved_by="kevin@cbc.com", totals={}, terms={})
    proposals.guard_approved(approved)  # does not raise


def test_sending_is_a_transition_off_generated() -> None:
    approved = proposals.approve(approved_by="kevin@cbc.com", totals={}, terms={})
    sent = proposals.mark_sent(approved, to="rebecca@cbc.com", channel="draft", actor="kevin@cbc.com")
    assert sent["status"] == "sent"
    assert sent["sentToEmail"] == "rebecca@cbc.com"
    assert sent["deliveryChannel"] == "draft", "nothing is transmitted from here (NFR-1)"


def test_a_superseded_proposal_names_its_replacement() -> None:
    first = proposals.approve(approved_by="kevin@cbc.com", totals={}, terms={})
    closed = proposals.supersede(first, by_id="p2")
    assert closed["status"] == "superseded"
    assert closed["supersededByProposalId"] == "p2"
