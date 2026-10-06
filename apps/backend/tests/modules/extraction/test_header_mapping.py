"""A schedule column is read by where it sits, not by how many cells precede it.

Every one of these locks in a way the parser was *silently* wrong: it produced a
plausible value from the wrong column, and nothing flagged it. That is the single
failure mode the take-off contract forbids - a field is either right, or blank.
"""
from __future__ import annotations

import pytest

from cbc.modules.extraction.infrastructure import schedule_parser as ps


def _row(cells, boxes, y=100.0):
    return {"cells": list(cells), "cell_boxes": [list(b) for b in boxes],
            "y": y, "text": " | ".join(cells)}


def _span(x0, x1):
    return (x0, 0.0, x1, 8.0)


# ── short aliases ───────────────────────────────────────────────────────────

def test_a_one_letter_alias_must_be_the_whole_cell() -> None:
    """`height` carries the alias "H", and "H" is in "WIDTH".

    Matched as a substring, `height` claimed the width column and every opening
    on that sheet came back square - 3030 for a 3'-0" x 7'-0" door.
    """
    assert ps._alias_matches("H", "H") is True
    assert ps._alias_matches("H", "WIDTH") is False
    assert ps._alias_matches("W", "WIDTH") is False
    # A longer alias still matches inside a composed header.
    assert ps._alias_matches("WIDTH", "DOOR WIDTH") is True


def test_width_and_height_map_to_their_own_columns() -> None:
    header = _row(
        ["Room Name", "Number", "Width", "Height", "Rating"],
        [_span(10, 40), _span(60, 80), _span(100, 120), _span(140, 160), _span(180, 200)],
    )
    mapping = ps._detect_header_map([header])
    spans = mapping["_x"]
    assert spans["width"] != spans["height"]
    assert spans["width"][0] == 100 and spans["height"][0] == 140


def test_a_number_column_is_the_door_mark() -> None:
    """"NUMBER" contains no "NO", so the whole header row was thrown away."""
    header = _row(
        ["Room Name", "Number", "Width", "Height"],
        [_span(10, 40), _span(60, 80), _span(100, 120), _span(140, 160)],
    )
    assert "door_number" in ps._detect_header_map([header])


def test_a_wall_stop_column_is_not_a_wall_type() -> None:
    """It fed `derive_frame_depths` a hardware column to look a throat up by."""
    header = _row(
        ["Door No.", "Width", "Height", "Wall/Floor Stop"],
        [_span(10, 40), _span(60, 80), _span(100, 120), _span(140, 200)],
    )
    assert "wall_type" not in ps._detect_header_map([header])


def test_a_real_wall_type_column_still_maps() -> None:
    header = _row(
        ["Door No.", "Width", "Height", "Wall Type"],
        [_span(10, 40), _span(60, 80), _span(100, 120), _span(140, 200)],
    )
    assert "wall_type" in ps._detect_header_map([header])


# ── stacked headers ─────────────────────────────────────────────────────────

def _stacked():
    """The Wendy's sheet: ROOM is a tier above the row naming WD / HGT / THK."""
    return [
        _row(["ROOM", "SIZE", "REMARKS"],
             [_span(144, 168), _span(266, 283), _span(622, 660)], y=194),
        _row(["DOOR", "HDW", "GLAZ", "TYPE", "MATL", "TYPE", "MATL", "GLASS"],
             [_span(72, 96), _span(353, 372), _span(393, 414), _span(431, 452),
              _span(466, 487), _span(503, 524), _span(539, 560), _span(573, 600)], y=198),
        _row(["MARK", "WD", "HGT", "THK", "GROUP", "TYPE"],
             [_span(72, 95), _span(224, 237), _span(267, 284), _span(312, 328),
              _span(348, 377), _span(393, 414)], y=208),
    ]


def test_a_column_is_read_by_position_not_by_index() -> None:
    """The winning tier has six cells; its data rows have thirteen.

    Mapping by index read every field one column to the left: `width` came back
    "VESTIBULE", `height` came back the width, `thickness` came back the height.
    """
    mapping = ps._detect_header_map(_stacked())
    data = _row(
        ["02", "VESTIBULE", "3'-0\"", "7'-0\"", "1 3/4\"", "02", "G-3", "A",
         "ALUM", "11", "ALUM", "YES", "NOTE: 8,9"],
        [_span(80, 88), _span(108, 151), _span(222, 238), _span(268, 283),
         _span(310, 330), _span(358, 367), _span(397, 410), _span(439, 444),
         _span(466, 488), _span(509, 518), _span(539, 561), _span(579, 594),
         _span(609, 668)],
        y=227,
    )
    assert ps._cell(data, mapping, "door_number") == "02"
    assert ps._cell(data, mapping, "width") == "3'-0\""
    assert ps._cell(data, mapping, "height") == "7'-0\""
    assert ps._cell(data, mapping, "thickness") == "1 3/4\""
    assert ps._cell(data, mapping, "hardware_set") == "02"


def test_a_tier_above_supplies_a_column_the_winner_missed() -> None:
    """ROOM is a tier up, so `room_name` came back null for every opening."""
    mapping = ps._detect_header_map(_stacked())
    assert mapping["_x"]["room_name"] == (144.0, 168.0)
    assert mapping["_x"]["notes"] == (622.0, 660.0)


def test_a_group_label_never_displaces_a_real_column() -> None:
    """"SIZE" spans WD / HGT / THK and its box sits over HGT."""
    spans = ps._detect_header_map(_stacked())["_x"]
    assert spans["height"] == (267.0, 284.0)
    assert spans.get("size") != spans["height"]


def test_an_empty_column_reads_blank_rather_than_a_neighbour() -> None:
    mapping = ps._detect_header_map(_stacked())
    sparse = _row(["07"], [_span(80, 88)], y=240)
    assert ps._cell(sparse, mapping, "door_number") == "07"
    assert ps._cell(sparse, mapping, "width") is None


# ── a hardware legend is not a schedule ─────────────────────────────────────

def test_a_hardware_legend_line_is_not_an_opening() -> None:
    """A legend shares the sheet and reads "3 | EA. | US10B | HAGER".

    Eleven came back as openings on one sheet, each with a quantity where the
    door number belongs. Those parts are `hardware_groups`' job.
    """
    mapping = ps._detect_header_map(_stacked())
    legend = _row(
        ["10B", "HAGER", "LL", "1", "EA. WEATHER STRIPPING", "873S-N-4284-MILL"],
        [_span(80, 95), _span(110, 150), _span(224, 237), _span(267, 284),
         _span(310, 400), _span(410, 500)],
        y=881,
    )
    assert ps._row_is_opening(legend, mapping) is False


def test_a_remark_may_still_say_ea() -> None:
    """"PROVIDE 2 EA. SILENCERS" is a note on a real opening, not a legend."""
    assert ps.HARDWARE_QTY_LINE.match("PROVIDE 2 EA. SILENCERS") is None
    assert ps.HARDWARE_QTY_LINE.match("EASEMENT") is None
    assert ps.HARDWARE_QTY_LINE.match("EA. ROTON HINGE") is not None


# ── a note number is not a fire rating ──────────────────────────────────────

def test_a_note_number_is_not_a_fire_rating() -> None:
    """A live run caught this one: opening 09 came back 20-minute rated.

    With no RATING column mapped, the search fell back to the whole row, and the
    row ended "NOTE: 1,15,16,20". Note 20 reads "G.C. TO ENSURE DOOR VIEWER TO
    BE ONE WAY GLASS". A rated door that is not rated is a wrong quote and a
    code problem, with nothing on the line to say anyone should look.
    """
    assert ps.FIRE_RATING_QUALIFIED.search("NOTE: 1,15,16,20") is None
    assert ps.FIRE_RATING_QUALIFIED.search("NOTE: 9,19") is None


@pytest.mark.parametrize(
    "text,expected",
    [("90 MIN", "90 MIN"), ("45 MINUTES", "45 MINUTES"), ("1 HR", "1 HR"), ("N/R", "N/R")],
)
def test_a_rating_that_names_its_unit_is_still_read(text, expected) -> None:
    match = ps.FIRE_RATING_QUALIFIED.search(text)
    assert match is not None and match.group(0) == expected


def test_a_bare_number_in_a_rating_column_is_still_a_rating() -> None:
    """Inside a column headed RATING, "90" means ninety minutes."""
    header = _row(
        ["Door No.", "Width", "Height", "Rating"],
        [_span(10, 40), _span(60, 80), _span(100, 120), _span(140, 200)],
    )
    mapping = ps._detect_header_map([header])
    data = _row(
        ["101", "3'-0\"", "7'-0\"", "90"],
        [_span(10, 40), _span(60, 80), _span(100, 120), _span(140, 200)],
        y=200,
    )
    assert ps._cell(data, mapping, "fire_rating") == "90"
    assert ps.FIRE_RATING.search("90") is not None


def _opening(cells, header_cells):
    boxes = [_span(10 + 60 * i, 50 + 60 * i) for i in range(len(header_cells))]
    mapping = ps._detect_header_map([_row(header_cells, boxes)])
    row = {**_row(cells, boxes[: len(cells)], y=200), "source_page": 3}
    return ps.parse_opening(row, mapping)


def test_a_rating_column_is_read_the_way_the_app_reads_a_rating() -> None:
    """The column went through a regex that knew 20/45/60/90/180 and "1 HR", so a
    90-minute door scheduled as "1-1/2 HR" came back unrated."""
    header = ["Door No.", "Width", "Height", "Rating"]
    assert _opening(["101", "3'-0\"", "7'-0\"", "1-1/2 HR"], header)["fire_rating"] == "90"
    assert _opening(["102", "3'-0\"", "7'-0\"", "NR"], header)["fire_rating"] == "NR"


def test_a_row_without_a_rating_column_is_not_rated_by_its_notes() -> None:
    opening = _opening(
        ["09", "3'-0\"", "7'-0\"", "NOTE: 1,15,16,20"], ["Door No.", "Width", "Height", "Remarks"]
    )
    assert opening["fire_rating"] is None


def test_the_wall_type_column_reaches_the_opening() -> None:
    """It was mapped from its header and then dropped, so every frame depth waited
    on an estimator."""
    opening = _opening(
        ["101", "3'-0\"", "7'-0\"", "W2"], ["Door No.", "Width", "Height", "Wall Type"]
    )
    assert opening["wall_type"] == "W2"


def test_a_rating_cell_says_smoke_label_and_hose_stream_beside_the_minutes() -> None:
    """Requirements 6.1: "20 MIN S" is a 20-minute, smoke-labeled door; "45 MINS" is
    neither; "NO HOSE STREAM" is the 20-minute door's listing."""
    header = ["Door No.", "Width", "Height", "Rating"]
    smoke = _opening(["104", "3'-0\"", "7'-0\"", "20 MIN S"], header)
    assert smoke["fire_rating"] == "20" and "smoke_label" in smoke["flags"]
    same = _opening(["107", "3'-0\"", "7'-0\"", "20 MIN"], header)
    assert smoke["confidence"] == same["confidence"], "a listing is not a doubt about the reading"
    plain = _opening(["105", "3'-0\"", "7'-0\"", "45 MINS"], header)
    assert plain["fire_rating"] == "45" and "smoke_label" not in plain["flags"]
    hose = _opening(["106", "3'-0\"", "7'-0\"", "20 MIN NO HOSE STREAM"], header)
    assert "no_hose_stream" in hose["flags"]


def test_a_door_in_a_bid_alternate_says_which() -> None:
    """FR-2: the alternate designation - from an ALT column, else the remarks."""
    by_column = _opening(["120", "3'-0\"", "7'-0\"", "2"], ["Door No.", "Width", "Height", "Alt"])
    assert by_column["alternate"] == "Alternate 2"
    by_remark = _opening(["121", "3'-0\"", "7'-0\"", "PART OF ADD ALT #1"], ["Door No.", "Width", "Height", "Remarks"])
    assert by_remark["alternate"] == "Alternate 1"
    plain = _opening(["122", "3'-0\"", "7'-0\"", "PROVIDE ALT. LEVER"], ["Door No.", "Width", "Height", "Remarks"])
    assert plain["alternate"] is None


def test_the_schedules_alternate_takes_the_bid_forms_name() -> None:
    from cbc.modules.extraction.api.line_items import _as_on_the_form

    assert _as_on_the_form("Alternate 1", ["Alt #1 - auto operators", "Alt #2"]) == "Alt #1 - auto operators"
    assert _as_on_the_form("Alternate 3", ["Alt #1"]) == "Alternate 3"


def test_a_temperature_rise_door_says_so() -> None:
    """Requirements 6.1: the label states the temperature rise - a stair door's core."""
    header = ["Door No.", "Width", "Height", "Rating"]
    for written in ("90 MIN 450° TEMP RISE", "60 MIN TEMP. RISE 250", "90 MIN 450 DEG MAX"):
        rise = _opening(["201", "3'-0\"", "7'-0\"", written], header)
        assert rise["fire_rating"] in ("90", "60") and "temperature_rise" in rise["flags"], written
    plain = _opening(["202", "3'-0\"", "7'-0\"", "90 MIN"], header)
    assert "temperature_rise" not in plain["flags"]
    assert rise["confidence"] == plain["confidence"], "a listing is not a doubt about the reading"
