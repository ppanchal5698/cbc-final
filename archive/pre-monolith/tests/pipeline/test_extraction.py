"""Extraction tests against the real Dutch Bros bid set.

The fixture is a genuine CAD export, so these tests exercise the awkward parts:
schedules that are not ruled tables, sizes written as explicit feet-inches rather
than 4-digit shorthand, and a door schedule with no fire-rating column at all.
"""
from __future__ import annotations

import pytest
import parse_schedule
from tests.shared import SCHEDULE_PAGE


def test_schedule_pages_are_located(fixture_pdf):
    pages = parse_schedule.find_schedule_pages(str(fixture_pdf))
    assert pages, "no schedule markers found in the bid set"

    by_page = {page["source_page"]: page["markers"] for page in pages}
    assert SCHEDULE_PAGE in by_page, f"sheet A2.2 (page {SCHEDULE_PAGE}) not identified"
    assert "DOOR SCHEDULE" in by_page[SCHEDULE_PAGE]
    assert "HARDWARE GROUPS" in by_page[SCHEDULE_PAGE]


def test_openings_are_extracted(fixture_pdf):
    openings = parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE)
    assert len(openings) >= 1, "no openings extracted from the door schedule"

    groups = {opening["hardware_set"] for opening in openings}
    assert "GROUP 1" in groups
    assert "GROUP 2" in groups


def test_every_opening_has_a_size_and_a_source_page(fixture_pdf):
    for opening in parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE):
        assert opening["source_page"] == SCHEDULE_PAGE, "source_page is mandatory (NFR-3)"
        assert opening["width"] and opening["height"], f"unresolved size: {opening['raw_row']}"
        assert 0.0 <= opening["confidence"] <= 1.0


def test_four_digit_notation():
    assert parse_schedule.parse_size("3070")["width"] == "3'-0\""
    assert parse_schedule.parse_size("3070")["height"] == "7'-0\""
    assert parse_schedule.parse_size("3670")["width"] == "3'-6\""
    assert parse_schedule.parse_size("3070")["notation"] == "4-digit"


def test_explicit_notation_is_also_handled():
    parsed = parse_schedule.parse_size("01 3' - 6\" | 7' - 0\" | A | 1")
    assert parsed["width"] == "3'-6\""
    assert parsed["height"] == "7'-0\""
    assert parsed["notation"] == "explicit"


def test_missing_size_is_not_invented():
    parsed = parse_schedule.parse_size("GROUP 1 | HM HMD")
    assert parsed["size"] is None and parsed["width"] is None


def test_missing_fire_rating_is_flagged_not_filled(fixture_pdf):
    """The fixture's door schedule has no rating column - that must surface, not vanish."""
    openings = parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE)
    for opening in openings:
        if opening["fire_rating"] is None:
            assert "fire_rating_missing" in opening["flags"]


def test_clustering_beats_ruled_table_detection(fixture_pdf):
    """Regression guard for the core parsing decision.

    The schedule sheet is dense CAD linework. If someone swaps the clustering
    approach for ruling-based table detection, this row disappears.
    """
    rows = parse_schedule.cluster_rows(str(fixture_pdf), SCHEDULE_PAGE)
    assert len(rows) > 100, "expected a dense CAD sheet"
    joined = " ".join(row["text"] for row in rows)
    assert "HARDWARE GROUPS" in joined
    assert "DOOR SCHEDULE" in joined


def test_frame_depth_follows_from_the_wall_it_sits_in():
    """The throat is not on the drawing - it follows from the wall construction.

    `wall_type` is described in the process flow as the field "which derives the
    frame depth", the five standard throats have been in reference-library all
    along, and nothing ever read them: neither real bid set produced a single
    frame_depth. A frame ordered to the wrong throat does not fit, and that is
    discovered on site.
    """
    from cbc.services.reference_library import depth_for_wall_type

    # What a schedule actually writes, not the table's own labels.
    assert depth_for_wall_type("CMU")["depth"] == "5-3/4"
    assert depth_for_wall_type('8" MASONRY')["depth"] == "5-3/4"
    assert depth_for_wall_type("MTL STUD W/ GYP")["depth"] == "5-7/8"
    assert depth_for_wall_type("wood-frame")["depth"] == "7-3/4"
    assert depth_for_wall_type('1/2" DRYWALL')["depth"] == "5-5/8"


def test_a_more_specific_wall_wins_over_a_general_one():
    """A 6-inch stud wall is 8-1/4, not the 5-7/8 that bare "stud" would give."""
    from cbc.services.reference_library import depth_for_wall_type

    assert depth_for_wall_type('6" METAL STUD W/ 5/8" GYP')["depth"] == "8-1/4"


@pytest.mark.parametrize("wall", [None, "", "   ", "unknown wall", "see structural"])
def test_an_unclear_wall_gets_no_depth_at_all(wall):
    """The table's own instruction: do NOT guess a depth, flag it for review."""
    from cbc.services.reference_library import depth_for_wall_type

    assert depth_for_wall_type(wall) is None
