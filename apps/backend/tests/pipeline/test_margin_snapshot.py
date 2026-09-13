"""A quoted line keeps the margin it was quoted at.

`collections.mongodb.md` §4.8, on the frozen snapshots that hang off an estimate
line: *"The snapshots are the important row. They are not caches and must never
be refreshed."*

`quote.reprice()` re-derived the margin from the *current* bands on every call
and persisted the result, so editing a margin band silently repriced every line
that had ever been priced under the old one - including lines on a quote already
sent. NFR-3 asks that every generated line be traceable to the reference-library
version in force when it was priced; a value that moves underneath you cannot be.

These tests fail against the code as it was.
"""
from __future__ import annotations

from cbc.modules.quoting.api import quote


def line(**overrides):
    row = {"division": "08 71 00", "cost": 100.0, "qty": 1, "margin": None}
    row.update(overrides)
    return row


def _bands(monkeypatch, commodity: float) -> None:
    """Point the live band lookup at a value we control."""
    from cbc.core import calc

    monkeypatch.setattr(calc, "bands", lambda: {"commodity": commodity})


def test_the_first_pricing_freezes_the_band_it_used(monkeypatch) -> None:
    _bands(monkeypatch, 0.27)
    rows = [line()]
    quote.reprice(rows, None, None)

    snapshot = rows[0]["marginSnapshot"]
    assert snapshot["rate"] == 0.27
    assert snapshot["band"] == "commodity"
    assert snapshot["overridden"] is False
    assert snapshot["resolvedFrom"] == "band"


def test_changing_a_band_does_not_reprice_a_quoted_line(monkeypatch) -> None:
    """The defect, stated directly."""
    _bands(monkeypatch, 0.27)
    rows = [line()]
    quote.reprice(rows, None, None)
    quoted_sell = rows[0]["sell"]

    _bands(monkeypatch, 0.40)  # purchasing edits the framework
    quote.reprice(rows, None, None)

    assert rows[0]["sell"] == quoted_sell, "a sent quote repriced itself"
    assert rows[0]["marginSnapshot"]["rate"] == 0.27


def test_a_new_line_after_a_band_change_uses_the_new_band(monkeypatch) -> None:
    """Freezing must not mean the framework can never change anything."""
    _bands(monkeypatch, 0.27)
    old = [line()]
    quote.reprice(old, None, None)

    _bands(monkeypatch, 0.40)
    new = [line()]
    quote.reprice(new, None, None)

    assert old[0]["marginSnapshot"]["rate"] == 0.27
    assert new[0]["marginSnapshot"]["rate"] == 0.40
    assert new[0]["sell"] != old[0]["sell"]


def test_an_estimator_override_wins_and_is_recorded_as_one(monkeypatch) -> None:
    """Matrix 6.1: bands are defaults the estimator adjusts by experience."""
    _bands(monkeypatch, 0.27)
    rows = [line(margin=0.15)]
    quote.reprice(rows, None, None)

    snapshot = rows[0]["marginSnapshot"]
    assert snapshot["rate"] == 0.15
    assert snapshot["overridden"] is True
    assert snapshot["resolvedFrom"] == "override"
    assert snapshot["band"] == "commodity", "the band it departed from is still recorded"


def test_an_override_replaces_a_frozen_band(monkeypatch) -> None:
    _bands(monkeypatch, 0.27)
    rows = [line()]
    quote.reprice(rows, None, None)

    rows[0]["margin"] = 0.15
    quote.reprice(rows, None, None)

    assert rows[0]["marginSnapshot"]["rate"] == 0.15
    assert rows[0]["marginSnapshot"]["overridden"] is True


def test_a_repriced_line_is_reported_as_changed_so_the_snapshot_persists(monkeypatch) -> None:
    """reprice() writes nothing; the caller persists what it reports."""
    _bands(monkeypatch, 0.27)
    rows = [line()]
    result = quote.reprice(rows, None, None)
    assert result["changed"] == rows

    settled = quote.reprice(rows, None, None)
    assert settled["changed"] == [], "a settled line was rewritten for no reason"


def test_an_unpriced_line_freezes_nothing(monkeypatch) -> None:
    """A MANUAL line has no cost, so there is no price to be traceable to."""
    _bands(monkeypatch, 0.27)
    rows = [line(cost=None)]
    quote.reprice(rows, None, None)
    assert rows[0].get("marginSnapshot") is None
    assert rows[0]["sell"] is None
