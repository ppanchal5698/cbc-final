"""The mechanical half of the review, asserted to be mechanical.

`quality-reviewer` was handed a thirteen-row finding table and asked to apply it
across every opening and every priced line. Most of those rows are facts about a
JSON file, and a model enumerating sixty of them by hand gets a different answer
each run - which is the one thing a review must not do.

These pin the derived findings: same input, same flags, every time; and the
agent's own findings survive the merge, because the rows it still owns are the
ones nothing here can see.
"""
from __future__ import annotations

import json

import pytest

from cbc.validation import review


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT", tmp_path)
    slug = "flagtest"
    (tmp_path / "projects" / slug / "extracted").mkdir(parents=True)
    (tmp_path / "projects" / slug / "priced").mkdir(parents=True)
    return slug, tmp_path / "projects" / slug


def _write(directory, relative, payload):
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fields(flags):
    return {(f["opening"], f["field"]) for f in flags}


def test_a_missing_rating_handing_or_size_is_flagged_high(project) -> None:
    slug, directory = project
    _write(directory, "extracted/door_schedule.json", {
        "openings": [
            {"door_number": "101", "source_page": 4, "bbox": [1, 2, 3, 4],
             "fire_rating": None, "handing": "LH", "size": "3070"},
        ]
    })
    flags = review.derive_flags(slug)
    assert ("Door 101", "fire_rating") in _fields(flags)
    assert ("Door 101", "handing") not in _fields(flags)
    rating = next(f for f in flags if f["field"] == "fire_rating")
    assert rating["severity"] == "high"
    assert rating["source_page"] == 4


def test_an_opening_with_no_bbox_is_flagged_for_traceability(project) -> None:
    """NFR-3: a record the estimator cannot find on the drawing is not traceable."""
    slug, directory = project
    _write(directory, "extracted/door_schedule.json", {
        "openings": [{"door_number": "102", "fire_rating": "90", "handing": "RH",
                      "size": "3070", "source_page": 4}]
    })
    assert ("Door 102", "bbox") in _fields(review.derive_flags(slug))


def test_low_confidence_is_flagged_at_the_documented_floor(project) -> None:
    slug, directory = project
    _write(directory, "extracted/door_schedule.json", {
        "openings": [
            {"door_number": "A", "confidence": 0.74, "fire_rating": "90",
             "handing": "LH", "size": "3070", "bbox": [1, 2, 3, 4]},
            {"door_number": "B", "confidence": 0.75, "fire_rating": "90",
             "handing": "LH", "size": "3070", "bbox": [1, 2, 3, 4]},
        ]
    })
    fields = _fields(review.derive_flags(slug))
    assert ("Door A", "confidence") in fields
    assert ("Door B", "confidence") not in fields, "0.75 is the accept threshold"


def test_an_unpriced_manual_line_is_flagged_medium(project) -> None:
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 101", "cost_source": "MANUAL", "cost": None},
        {"line_id": "L2", "group": "Door 102", "cost_source": "LIST_X_MULTIPLIER", "cost": 42.0},
    ]})
    flags = review.derive_flags(slug)
    assert ("Door 101", "cost") in _fields(flags)
    assert ("Door 102", "cost") not in _fields(flags)


def test_a_below_band_margin_is_flagged_against_the_real_floor(project) -> None:
    """NFR-8. The floor comes from calc.validate_margin on the division's band."""
    from cbc.core import calc
    from cbc.services import pricing

    band = pricing.band_for_division("08 11")
    floor = calc.bands()[band]
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 1", "division": "08 11",
         "margin": floor - 0.05, "cost_source": "LIST_X_MULTIPLIER", "cost": 10},
        {"line_id": "L2", "group": "Door 2", "division": "08 11",
         "margin": floor, "cost_source": "LIST_X_MULTIPLIER", "cost": 10},
    ]})
    fields = _fields(review.derive_flags(slug))
    assert ("Door 1", "margin") in fields
    assert ("Door 2", "margin") not in fields, "at the floor is not below it"


def test_an_unknown_project_state_leaves_sales_tax_unresolved(project) -> None:
    """Ohio and Kentucky are taxed. Unknown is not the same as untaxed."""
    slug, directory = project
    assert ("quote", "sales_tax") in _fields(review.derive_flags(slug))

    _write(directory, "extracted/scope_metadata.json", {"state": "OH"})
    assert ("quote", "sales_tax") not in _fields(review.derive_flags(slug))


def test_an_out_of_scope_item_is_reported_but_not_priced(project) -> None:
    slug, directory = project
    _write(directory, "extracted/scope_summary.json", {
        "out_of_scope_items": [
            {"item": "Kawneer 541T storefront", "reason": "aluminum/glass storefront",
             "source_page": 14}
        ]
    })
    flags = review.derive_flags(slug)
    found = next(f for f in flags if f["field"] == "out_of_scope")
    assert found["severity"] == "low"
    assert found["source_page"] == 14


def test_the_same_input_gives_the_same_flags(project) -> None:
    """The property the whole module exists for."""
    slug, directory = project
    _write(directory, "extracted/door_schedule.json", {
        "openings": [{"door_number": str(n), "source_page": 4} for n in range(20)]
    })
    first = review.derive_flags(slug)
    assert first == review.derive_flags(slug)
    assert len(first) > 20


def test_the_merge_keeps_what_only_the_agent_could_have_found(project) -> None:
    """Counts against the plans, silent inference, prior quotes, RFIs."""
    slug, _ = project
    derived = [{"opening": "Door 1", "field": "fire_rating", "severity": "high",
                "note": "derived", "derived": True}]
    existing = [
        {"opening": "Door 1", "field": "fire_rating", "severity": "low", "note": "stale"},
        {"opening": "bid set", "field": "count_reconcile", "severity": "high",
         "note": "62 openings extracted, 68 door tags on the plans"},
    ]
    merged = review.merge(derived, existing)
    assert {(f["opening"], f["field"]) for f in merged} == {
        ("Door 1", "fire_rating"),
        ("bid set", "count_reconcile"),
    }
    rating = next(f for f in merged if f["field"] == "fire_rating")
    assert rating["note"] == "derived", "the derived flag owns its field"


def test_a_bare_array_priced_file_still_derives_flags(project) -> None:
    slug, directory = project
    _write(directory, "priced/line_items.json", [
        {"line_id": "MAN-1", "cost_source": "MANUAL", "cost": None},
    ])
    flags = review.derive_flags(slug)
    assert ("MAN-1", "cost") in _fields(flags)


def test_write_flags_is_idempotent(project) -> None:
    """It reads what it wrote last time; running twice must not double the file."""
    slug, directory = project
    _write(directory, "extracted/door_schedule.json", {
        "openings": [{"door_number": "101", "source_page": 4}]
    })
    first = review.write_flags(slug)
    assert review.write_flags(slug) == first

    saved = json.loads((directory / "review" / "review_flags.json").read_text(encoding="utf-8"))
    assert len(saved) == first
