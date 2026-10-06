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


# ── a stacked DOOR: / FRAME: header, as the Shakopee reimage set prints it ──────

def _box(x0, x1, y):
    return [x0, y, x1, y + 9.0]


def _shakopee_rows():
    """Page 4 of the Shakopee set, as the words fall: the frame's MAT'L and TYPE
    printed close enough to cluster as one cell, a notes cell set a few points
    below its row, and a door type letter set a little above."""
    def row(y, cells):
        return {"y": y, "source_page": 4, "cells": [c[0] for c in cells],
                "cell_boxes": [_box(c[1], c[2], y) for c in cells],
                "cell_words": [c[3] if len(c) > 3 else [(c[1], c[2], c[0])] for c in cells],
                "text": " | ".join(c[0] for c in cells)}

    return [
        row(151.0, [("DOOR:", 458, 509), ("FRAME:", 659, 719)]),
        row(178.1, [("N0.", 458, 475), ("WIDTH", 493, 520), ("HGT.", 539, 558), ("MAT'L", 580, 607),
                    ("TYPE", 623, 643), ("MAT'L", 662, 690), ("TYPE", 707, 728), ("GROUP", 747, 777),
                    ("NOTES", 808, 838)]),
        row(209.2, [("1", 464, 467), ('36"', 503, 523), ('84"', 544, 564), ("HPL", 583, 599), ("C", 633, 639),
                    ("ALUM E, 3'-4\"", 668, 741, [(668, 690, "ALUM"), (700, 706, "E,"), (710, 741, "3'-4\"")]),
                    ("5", 769, 776), ("TOILET: GC TO VERIFY WATER SUPPLY", 1024, 1342)]),
        row(212.3, [("DOOR PRE-HUNG IN FRAME, OPTIONAL ARM PULL", 810, 980)]),
        row(238.1, [("TOILET SEAT: TOTO SC534", 1087, 1205)]),
        row(242.8, [("2", 464, 470), ('36"', 503, 523), ('84"', 544, 564), ("HPL", 583, 599), ("C", 633, 639),
                    ("ALUM E, 3'-4\"", 668, 741, [(668, 690, "ALUM"), (700, 706, "E,"), (710, 741, "3'-4\"")]),
                    ("5", 769, 776)]),
        row(275.9, [("E", 630, 636)]),
        row(277.1, [("3", 465, 471), ('28"', 502, 522), ('60"', 545, 567), ("HPL", 588, 604),
                    ("ALUM E, 2'-8\"", 667, 741, [(667, 690, "ALUM"), (700, 706, "E,"), (710, 741, "2'-8\"")]),
                    ("6", 769, 776), ("DOOR PRE-HUNG IN FRAME", 810, 903)]),
    ]


def test_a_cell_printed_off_its_rows_baseline_joins_the_row() -> None:
    rows = _shakopee_rows()
    mapping = ps._detect_header_map(rows)
    merged = ps._attach_fragments(rows, mapping)
    door = {r["cells"][0]: r for r in merged if r["cells"] and r["cells"][0] in ("1", "2", "3")}
    assert door["1"]["cells"][-2:] == ["5", "DOOR PRE-HUNG IN FRAME, OPTIONAL ARM PULL"] or \
        "DOOR PRE-HUNG IN FRAME, OPTIONAL ARM PULL" in door["1"]["cells"]
    assert "E" in door["3"]["cells"] and door["3"]["cells"].index("E") == 4, "the type letter is the type column"
    assert not any("TOILET SEAT" in c for c in door["2"]["cells"]), "the plumbing notes beside the table stay out"


def test_the_frames_columns_under_a_frame_label_are_the_frames() -> None:
    rows = _shakopee_rows()
    mapping = ps._detect_header_map(rows)
    assert (mapping["frame_material"], mapping["frame_type"]) == (5, 6)
    merged = ps._attach_fragments(rows, mapping)
    one = next(r for r in merged if r["cells"][0] == "1")
    opening = ps.parse_opening(one, mapping)
    assert (opening["frame_material"], opening["frame_type"]) == ("AL", "E, 3'-4\"")
    assert opening["notes"] == "DOOR PRE-HUNG IN FRAME, OPTIONAL ARM PULL" and opening["door_type"] == "C"
    three = ps.parse_opening(next(r for r in merged if r["cells"][0] == "3"), mapping)
    assert three["door_type"] == "E" and three["size"] == "2450"


def test_a_size_four_digits_cannot_write_is_still_a_size() -> None:
    assert ps.parse_size('34" 84"')["size"] == "2'-10\" x 7'-0\""
    assert ps.parse_size("2'-10\" x 7'-0\"")["size"] == "2'-10\" x 7'-0\""
    assert ps.parse_size('36" 84"')["size"] == "3070"


def test_a_field_the_row_leaves_blank_is_not_a_doubt_about_the_reading() -> None:
    opening = _opening(["101", "3'-0\"", "7'-0\"", "5"], ["Door No.", "Width", "Height", "HW Set"])
    assert {"fire_rating_missing", "handing_missing", "finish_missing"} <= set(opening["flags"])
    assert opening["confidence"] == 1.0
    no_set = _opening(["102", "3'-0\"", "7'-0\""], ["Door No.", "Width", "Height"])
    assert no_set["confidence"] < 1.0, "a door with no hardware set is a gap in the reading"


# ── a header of rotated words, as the Evernorth schedule prints it ─────────────

def _evernorth_rows():
    """Page 21 of the Evernorth set, as the words fall: each column labelled by a
    stack of rotated words (DOOR under NUMBER, PANEL under TYPE), the frame's
    MATERIAL the same word as the door's, and door 100's width and height close
    enough to cluster as one cell."""
    def row(y, cells):
        return {"y": y, "source_page": 21, "cells": [c[0] for c in cells],
                "cell_boxes": [list(c[1]) for c in cells],
                "cell_words": [c[2] if len(c) > 2 else [(c[1][0], c[1][2], c[0])] for c in cells],
                "text": " | ".join(c[0] for c in cells)}

    def label(x, y0):
        return (x, y0, x + 17.0, 188.5)

    def cell(x0, x1, y):
        return (x0, y, x1, y + 12.9)

    return [
        row(93.4, [("NUMBER", label(195.0, 93.4))]),
        row(111.4, [("TYPE", label(330.1, 111.4)), ("TYPE", label(753.1, 108.6)), ("RATING", label(1168.7, 109.3))]),
        row(117.0, [("HARDWARE", label(1132.7, 115.6))]),
        row(126.0, [("MATERIAL", label(423.4, 126.0)), ("MATERIAL", label(816.1, 126.0))]),
        row(141.3, [("HEIGHT", label(285.1, 141.3))]),
        row(147.5, [("WIDTH", label(244.5, 147.5)), ("PANEL", label(330.1, 147.5)), ("FRAME", label(753.1, 144.8))]),
        row(151.0, [("DOOR", label(195.0, 151.0))]),
        row(160.0, [("FIRE", label(1168.7, 160.0))]),
        row(202.7, [("100", cell(196.1, 212.0, 202.7)),
                    ("5' - 7 1/2\" 9' - 0\"", cell(233.8, 306.4, 202.7),
                     [(233.8, 241.0, "5'"), (243.0, 247.0, "-"), (249.0, 254.0, "7"), (256.0, 265.8, "1/2\""),
                      (282.2, 288.0, "9'"), (290.0, 294.0, "-"), (296.0, 306.4, "0\"")]),
                    ("DD", cell(332.4, 346.1, 202.7)), ("EXISTING", cell(410.5, 454.8, 202.7)),
                    ("5", cell(759.5, 764.8, 202.7)), ("EXISTING", cell(803.2, 847.6, 202.7))]),
        *[row(y, [(mark, cell(196.1, 212.0, y)), (width, cell(241.6, 265.8, y)), ("7' - 0\"", cell(282.2, 306.4, y)),
                  (kind, cell(332.4, 346.1, y)), ("TBD", cell(538.1, 557.1, y)), ("1 3/4\"", cell(611.1, 635.6, y)),
                  ("GL-2", cell(677.8, 698.9, y)), ("1", cell(759.5, 764.8, y)), ("HM", cell(817.9, 832.6, y)),
                  ("PT-4", cell(888.9, 909.5, y)), ("NO", cell(974.9, 989.2, y)), ("02", cell(1136.5, 1147.0, y)),
                  ("YES", cell(1197.7, 1216.7, y))])
          for y, mark, width, kind in ((215.7, "101", "5' - 0\"", "DD"), (228.6, "103", "3' - 0\"", "B"))],
        row(241.6, [("106", cell(196.1, 212.0, 241.6)), ("3' - 0\"", cell(241.6, 265.8, 241.6)),
                    ("7' - 0\"", cell(282.2, 306.4, 241.6)), ("A", cell(336.0, 342.0, 241.6)),
                    ("EXISTING", cell(410.5, 454.8, 241.6)), ("TBD", cell(538.1, 557.1, 241.6)),
                    ("1 3/4\"", cell(611.1, 635.6, 241.6)), ("NO", cell(681.0, 696.0, 241.6)),
                    ("3", cell(759.5, 764.8, 241.6)), ("EXISTING", cell(803.2, 847.6, 241.6)),
                    ("PT-4", cell(888.9, 909.5, 241.6)), ("EXISTING", cell(960.0, 1004.4, 241.6)),
                    ("1' - 6\"", cell(1033.0, 1056.0, 241.6)), ("03", cell(1136.5, 1147.0, 241.6)),
                    ("NO", cell(1197.7, 1213.0, 241.6))]),
    ]


def test_a_header_of_rotated_words_is_read_column_by_column() -> None:
    rows = _evernorth_rows()
    mapping = ps._detect_header_map(rows)
    spans = mapping["_x"]
    assert spans["hardware_set"][0] == 1132.7 and spans["fire_rating"][0] == 1168.7
    assert spans["door_material"][0] == 423.4 and spans["frame_material"][0] == 816.1, \
        "the MATERIAL right of the FRAME label is the frame's"
    assert spans["door_type"][0] == 330.1 and spans["frame_type"][0] == 753.1
    one = ps.parse_opening(next(r for r in rows if r["cells"][0] == "101"), mapping)
    assert (one["hardware_set"], one["frame_type"], one["frame_material"], one["door_type"]) == ("GROUP 02", "1", "HM", "DD")
    assert one["door_material"] is None, "a blank material column is blank - GL-2 is the glazing"


def test_a_door_whose_size_carries_a_fraction_is_an_opening() -> None:
    rows = _evernorth_rows()
    mapping = ps._detect_header_map(rows)
    hundred = next(r for r in rows if r["cells"][0] == "100")
    assert ps._row_is_opening(hundred, mapping)
    opening = ps.parse_opening(hundred, mapping)
    assert (opening["width"], opening["height"]) == ("5'-7 1/2\"", "9'-0\"")
    assert ps.parse_size("9'-0\" 10'-0\"")["size"] == "9'-0\" x 10'-0\"", "no four-digit code holds a 10-ft door"


def test_a_level_header_is_not_read_as_stacked_words() -> None:
    """A202 sets its title and a vendor note over a level two-tier header."""
    def row(y, cells):
        return {"y": y, "cells": [c[0] for c in cells], "cell_boxes": [[c[1], y, c[2], y + 9.0] for c in cells],
                "text": " | ".join(c[0] for c in cells)}

    rows = [
        row(913.0, [("OPENING SCHEDULE", 1502, 1634), ("NATIONAL ACCOUNT DOOR AND FRAME SUPPLIER", 1708, 2374)]),
        row(943.0, [("FRAME", 1738, 1765), ("DOOR", 1944, 1967)]),
        row(950.0, [("OPNG.", 1495, 1520), ("OPENING", 1552, 1588), ("FIRE", 2037, 2054), ("HARDWARE NOTES:", 2068, 2151)]),
        row(983.2, [("100A", 1497, 1520), ("6'-4\" x 8'-11 3/8\"", 1623, 1700), ("B", 1907, 1913), ("ALUM.", 1943, 1970)]),
        row(1135.1, [("102", 1500, 1515), ("3'-4\" x7'-2\"", 1623, 1700), ("A", 1907, 1913), ("PC", 1949, 1960)]),
    ]
    assert ps._stacked_header(rows) is None


def test_a_column_the_header_gives_several_fields_is_no_ones_blank() -> None:
    """DTGO's header pins door type, material and finish to one column; a blank
    there says nothing, so the row's own HM still reads as its material."""
    collapsed = {"door_number": 0, "door_type": 2, "door_material": 2, "finish": 2,
                 "_x": {"door_material": (100.0, 120.0), "door_number": (10.0, 20.0)}}
    assert not ps._column_of_its_own(collapsed, "door_material")
    assert ps._column_of_its_own(collapsed, "door_number")
