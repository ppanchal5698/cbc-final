"""The chain has to be able to finish on a bid whose drawings are simply quiet.

`extraction_review_verdict` needs fire_rating, handing, finish and size on every
opening. The first production set prints neither a fire rating - no FIRE RATING
column exists on that schedule, and the notes and Div 08 specs carry none - nor
handing, which is drawn as a swing arc rather than written. Completeness came out
0/6, the bid parked at `extraction_needs_review`, and autopilot could never reach
pricing. The take-off was correct; the gate could not be satisfied.

Two things were wrong and both are fixed here: out-of-scope openings were scored
like any other, and `extraction_needs_review` was a dead end rather than a flag.
"""
from __future__ import annotations

import json

from cbc.modules.extraction.api.validation import contracts
from cbc.modules.extraction.api.validation.review import reconcile_flags
from cbc.modules.projects.api import saga


def _write(tmp_path, monkeypatch, openings):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from cbc.shared.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    root = tmp_path / "bid" / "extracted"
    root.mkdir(parents=True, exist_ok=True)
    (root / "line_items.json").write_text(json.dumps({"openings": openings}), encoding="utf-8")
    return "bid"


def _opening(mark, **over):
    row = {
        "door_number": mark,
        "fire_rating": "90 min",
        "handing": "LH",
        "finish": "US26D (626)",
        "size": "3068",
        "confidence": 0.9,
    }
    row.update(over)
    return row


def test_storefront_openings_do_not_drag_the_takeoff_under_the_floor(tmp_path, monkeypatch):
    """Two of six openings on the first real set were out-of-scope aluminium."""
    slug = _write(tmp_path, monkeypatch, [
        _opening("02", in_scope=False, fire_rating=None, handing=None),
        _opening("03", in_scope=False, fire_rating=None, handing=None),
        _opening("05"),
        _opening("06"),
    ])

    assert contracts.extraction_review_verdict(slug) == "ok"


def test_a_genuinely_incomplete_takeoff_still_asks_for_review(tmp_path, monkeypatch):
    """The gate must still fire on in-scope openings that are actually missing."""
    slug = _write(tmp_path, monkeypatch, [
        _opening("05", fire_rating=None, handing=None),
        _opening("06", fire_rating=None, handing=None),
        _opening("08"),
    ])

    assert contracts.extraction_review_verdict(slug) == "needs_review"


def test_needs_review_advances_the_chain_instead_of_ending_it():
    """The estimator gate is at delivery, not at pricing - nothing is sent either way."""
    assert saga.can_advance("extract_bid_set", "extraction_needs_review") is True
    assert saga.can_advance("extract_bid_set", "extraction_done") is True
    # A failure still stops it.
    assert saga.can_advance("extract_bid_set", "awaiting_manual_retry") is False
    assert saga.can_advance("extract_bid_set", "extracting") is False


def test_a_flag_contradicted_by_its_own_field_is_dropped():
    """Every row of a real bid arrived flagged `finish_missing` carrying a finish."""
    opening = {
        "finish": "US26D (626)",
        "size": "3068",
        "fire_rating": None,
        "handing": None,
        "flags": ["finish_missing", "fire_rating_missing", "out_of_scope_storefront"],
    }

    flags = reconcile_flags(opening)

    assert "finish_missing" not in flags, "the finish is right there on the row"
    assert "fire_rating_missing" in flags, "genuinely absent, so it stays"
    assert "handing_missing" in flags, "empty and unflagged - the gap must not hide"
    assert "out_of_scope_storefront" in flags, "not a field flag; left alone"


def test_reconciling_twice_changes_nothing():
    """An unchanged opening must not rewrite the artifact and bump its version."""
    opening = {"finish": "US26D", "size": "3068", "fire_rating": None, "handing": None,
               "flags": ["finish_missing"]}
    once = reconcile_flags(opening)
    assert reconcile_flags({**opening, "flags": once}) == once
