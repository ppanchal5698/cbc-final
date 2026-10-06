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

from cbc.modules.extraction.api.validation import review
from cbc.modules.pricing.api import reference_store


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = "flagtest"
    (tmp_path / "projects" / slug / "extracted").mkdir(parents=True)
    (tmp_path / "projects" / slug / "priced").mkdir(parents=True)
    reference_store.use_memory({})  # the seed tier sheet and margins, never a database
    yield slug, tmp_path / "projects" / slug
    reference_store.use_memory(None)


def _write(directory, relative, payload):
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fields(flags):
    return {(f["opening"], f["field"]) for f in flags}


def test_a_missing_rating_handing_or_size_is_flagged_high(project) -> None:
    slug, directory = project
    _write(directory, "extracted/line_items.json", {
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
    _write(directory, "extracted/line_items.json", {
        "openings": [{"door_number": "102", "fire_rating": "90", "handing": "RH",
                      "size": "3070", "source_page": 4}]
    })
    assert ("Door 102", "bbox") in _fields(review.derive_flags(slug))


def test_low_confidence_is_flagged_at_the_documented_floor(project) -> None:
    slug, directory = project
    _write(directory, "extracted/line_items.json", {
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
    from cbc.modules.pricing.api import calc
    from cbc.modules.pricing.api import pricing

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
    _write(directory, "extracted/line_items.json", {
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
    _write(directory, "extracted/line_items.json", {
        "openings": [{"door_number": "101", "source_page": 4}]
    })
    first = review.write_flags(slug)
    assert review.write_flags(slug) == first

    saved = json.loads((directory / "review" / "review_flags.json").read_text(encoding="utf-8"))
    assert len(saved) == first


def test_a_line_priced_from_an_excluded_vendor_is_flagged_out_of_scope(project) -> None:
    """.claude/guides/takeoff.md: an excluded vendor is flagged whatever price the line carries."""
    reference_store.use_memory({"vendor_tiers": {"data": {"vendors": [], "excluded": [
        {"name": "American Dryer", "reason": "No longer used"},
    ]}}})
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "manufacturer": "American Dryer Inc.", "cost": 410.0, "source_page": 12},
        {"line_id": "L2", "vendor": "World Dryer", "cost": 395.0, "source_page": 12},
    ]})
    flags = [f for f in review.derive_flags(slug) if f["field"] == "out_of_scope"]
    assert [(f["opening"], f["severity"], f["source_page"]) for f in flags] == [("L1", "high", 12)]
    assert "American Dryer" in flags[0]["note"]


def _blocking(flags):
    return {(f["opening"], f["field"]): f["blocking"] for f in flags}


def test_blocking_is_set_per_kind(project) -> None:
    """Severity is display; blocking is what holds the approval."""
    slug, directory = project
    _write(directory, "extracted/scope_summary.json", {"fire_ratings_present": True})
    _write(directory, "extracted/scope_metadata.json", {"brand_mismatch_warning": "Wendys vs Arbys"})
    _write(directory, "extracted/line_items.json", {"openings": [
        {"door_number": "101", "source_page": 4, "bbox": [1, 2, 3, 4],
         "fire_rating": None, "handing": None, "size": "3070"},
    ]})
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 101", "cost_source": "MANUAL", "cost": None},
    ]})
    blocking = _blocking(review.derive_flags(slug))
    assert blocking[("Door 101", "fire_rating")] is True
    assert blocking[("Door 101", "handing")] is False
    assert blocking[("Door 101", "cost")] is True
    assert blocking[("bid set", "project_identity")] is True
    assert blocking[("quote", "sales_tax")] is False


def test_an_unpriced_alternate_is_shown_but_holds_nothing(project) -> None:
    """An alternate is not in the bid's total, so a price it still lacks does not hold the bid."""
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 101", "cost_source": "MANUAL", "cost": None},
        {"line_id": "L2", "group": "Door 102", "cost_source": "DISTRIBUTOR_MANUAL", "cost": None,
         "alternate_group": "Allegion as specified"},
    ]})
    blocking = _blocking(review.derive_flags(slug))
    assert blocking[("Door 101", "cost")] is True
    assert blocking[("Door 102", "cost")] is False


def test_a_missing_rating_does_not_block_in_a_set_with_no_ratings(project) -> None:
    slug, directory = project
    _write(directory, "extracted/line_items.json", {"openings": [
        {"door_number": "101", "bbox": [1, 2, 3, 4], "handing": "LH", "size": "3070"},
    ]})
    assert _blocking(review.derive_flags(slug))[("Door 101", "fire_rating")] is False


def test_a_below_band_margin_with_a_reason_is_advisory(project) -> None:
    from cbc.modules.pricing.api import calc, pricing

    floor = calc.bands()[pricing.band_for_division("08 11")]
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 1", "division": "08 11", "margin": floor - 0.05,
         "cost_source": "LIST_X_MULTIPLIER", "cost": 10},
        {"line_id": "L2", "group": "Door 2", "division": "08 11", "margin": floor - 0.05,
         "cost_source": "LIST_X_MULTIPLIER", "cost": 10,
         "margin_overridden": True, "margin_override_reason": "matching the GC's number"},
    ]})
    blocking = _blocking(review.derive_flags(slug))
    assert blocking[("Door 1", "margin")] is True
    assert blocking[("Door 2", "margin")] is False


def test_frp_with_pending_constants_blocks(project) -> None:
    """The seed constants are PENDING (Open Item 5), so FRP rows cannot be quoted yet."""
    slug, directory = project
    assert ("bid set", "frp_constants_pending") not in _fields(review.derive_flags(slug))

    _write(directory, "extracted/frp_takeoff.json", {"areas": [{"location": "Kitchen"}]})
    flag = next(f for f in review.derive_flags(slug) if f["field"] == "frp_constants_pending")
    assert flag["blocking"] is True
    assert flag["severity"] == "high"


def test_locally_parsed_pages_are_flagged_as_advisory(project) -> None:
    slug, directory = project
    _write(directory, "extracted/_parse_status.json", {"documents": [
        {"documentId": "d1", "filename": "A.pdf", "state": "parsed", "error": None,
         "fallbackPages": [9, 10]},
    ]})
    flag = next(f for f in review.derive_flags(slug) if f["field"] == "parse_fallback")
    assert flag["blocking"] is False
    assert flag["severity"] == "medium"
    assert "9, 10" in flag["note"]
    assert not [f for f in review.derive_flags(slug) if f["field"] == "document_not_parsed"]


def test_a_cleared_derived_flag_does_not_survive_in_the_saved_file(project) -> None:
    """Otherwise the approval gate stays shut after the estimator enters the cost."""
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 101", "cost_source": "MANUAL", "cost": None},
    ]})
    review.write_flags(slug)
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "L1", "group": "Door 101", "cost_source": "MANUAL", "cost": 120.0},
    ]})
    assert ("Door 101", "cost") not in _fields(review.read_flags(slug))


def test_an_agent_flag_never_blocks(project) -> None:
    merged = review.merge([], [{"opening": "bid set", "field": "rfi", "severity": "high",
                                "note": "RFI", "blocking": True}])
    assert merged[0]["blocking"] is False


def test_the_seed_tier_sheet_excludes_the_vendors_the_scope_rule_names(project) -> None:
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "P1", "vendor": "Scranton Products"},
    ]})
    assert ("P1", "out_of_scope") in _fields(review.derive_flags(slug))


def test_a_door_with_no_rating_blocks_when_its_schedule_rates_the_others(project) -> None:
    """Rule 1 (requirements 6.1), read off the doors themselves: the summary flag it
    waited for was written by no code path, so it never held anything."""
    slug, directory = project
    _write(directory, "extracted/line_items.json", {"openings": [
        {"door_number": "101", "bbox": [1, 2, 3, 4], "handing": "LH", "size": "3070", "fire_rating": "1-1/2 HR"},
        {"door_number": "102", "bbox": [1, 2, 3, 4], "handing": "LH", "size": "3070", "fire_rating": None},
        {"door_number": "100A", "bbox": [1, 2, 3, 4], "handing": "LH", "size": "6070", "fire_rating": None,
         "in_scope": False},
    ]})
    blocking = _blocking(review.derive_flags(slug))
    assert blocking[("Door 102", "fire_rating")] is True
    assert blocking[("Door 100A", "fire_rating")] is False, "a door CBC is not quoting holds nothing"


def test_an_exit_device_on_a_rated_door_asks_for_listed_fire_exit_hardware(project) -> None:
    slug, directory = project
    _write(directory, "priced/line_items.json", {"lines": [
        {"line_id": "1:01", "group": "01", "cost_source": "CATALOG_BASELINE", "cost": 412.0,
         "flags": ["fire_exit_hardware_required"]},
    ]})
    [flag] = [f for f in review.derive_flags(slug) if f["field"] == "fire_rating"]
    assert flag["severity"] == "high" and "fire exit hardware" in flag["note"]
