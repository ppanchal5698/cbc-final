"""Bid status and outcome reconcile against each other, and leave a trail.

`_apply_bid_state` is pure, so this needs no client, no Mongo and no fixtures -
just the two rules an estimator would state, and the transitions that have to
reach `statusHistory` for hit rate to be computable later.
"""
from __future__ import annotations

from cbc.modules.projects.features.UpdateProject import _apply_bid_state


def test_marking_not_bid_clears_any_outcome():
    changes = {"bidStatus": "not_bid"}
    _apply_bid_state(changes, {"bidStatus": "bid", "outcome": "won"})
    assert changes["outcome"] == ""


def test_recording_an_outcome_means_it_was_bid_after_all():
    changes = {"outcome": "lost"}
    _apply_bid_state(changes, {"bidStatus": "not_bid", "outcome": ""})
    assert changes["bidStatus"] == "bid"


def test_clearing_an_outcome_leaves_the_bid_open_and_still_bid():
    changes = {"outcome": ""}
    _apply_bid_state(changes, {"bidStatus": "bid", "outcome": "won"})
    assert changes["outcome"] == ""
    # An empty outcome is not a reason to touch bid status.
    assert "bidStatus" not in changes


def test_every_change_is_reported_for_the_status_history():
    changes = {"outcome": "won"}
    transitions = _apply_bid_state(changes, {"bidStatus": "not_bid", "outcome": ""})
    assert {"field": "outcome", "from": "", "to": "won"} in transitions
    # The forced bid status is a real transition too, not a silent side effect.
    assert {"field": "bidStatus", "from": "not_bid", "to": "bid"} in transitions


def test_a_no_op_edit_records_nothing():
    changes = {"bidStatus": "bid", "outcome": "won"}
    assert _apply_bid_state(changes, {"bidStatus": "bid", "outcome": "won"}) == []


def test_an_unrelated_edit_is_left_alone():
    changes = {"name": "Renamed"}
    assert _apply_bid_state(changes, {"bidStatus": "bid", "outcome": ""}) == []
    assert changes == {"name": "Renamed"}
