"""A take-off becomes the lines it is priced in: every count right, nothing guessed."""
from __future__ import annotations

import pytest

from cbc.modules.quoting.domain import takeoff


@pytest.mark.parametrize(("written", "each"), [
    (3, 3.0), ("3", 3.0), ("3 EA", 3.0), ("3 EA.", 3.0),
    ("1 1/2 PR", 3.0), ("1 1/2 PR.", 3.0), ("2PR", 4.0), ("1-1/2", 1.5), ("1/2", 0.5), ("(3)", 3.0),
    ("", None), (None, None), ("PR", None), ("two", None), (0, None), (True, None),
])
def test_a_quantity_is_read_as_written_and_a_pair_is_two(written, each) -> None:
    assert takeoff.quantity(written)[0] == each


@pytest.mark.parametrize(("reference", "key"), [
    ("SET 01", "1"), ("GROUP 1", "1"), ("HW-1", "1"), ("HW1", "1"), ("01", "1"),
    ("GROUP 7: RESTROOM", "7"), ("07A", "7A"), ("Set 7a", "7A"), ("GROUP 12 (rev)", "12"), ("none", None),
])
def test_every_way_of_writing_a_set_reference_is_one_set(reference, key) -> None:
    assert takeoff.set_key(reference) == key


SETS = [
    {"name": "01", "source_page": 16, "items": [
        {"qty": "1 1/2 PR.", "part": "BB1279", "manufacturer": "Hager", "finish": "US26D",
         "description": 'HINGES 4 1/2" x 4 1/2"'},
        {"qty": "1", "part": "3553", "manufacturer": "Hager", "finish": "US26D", "description": "ENTRY LOCK"},
        {"qty": None, "part": "236W", "manufacturer": "Hager", "description": "WALL STOP"},
        {"qty": "1", "part": "1792NL", "manufacturer": "Falcon", "notes": "supplied by landlord"},
    ]},
    {"name": "02", "items": []},
    {"name": "05", "items": [{"qty": "1", "part": "X"}]},
]
OPENINGS = [
    {"mark": "101", "set": "GROUP 01", "source_page": 12},
    {"mark": "102", "set": "SET 1", "source_page": 12, "count": 2},  # the row stands for two doors
    {"mark": "103", "set": "GROUP 02"},
    {"mark": "104", "set": "GROUP 09"},
]


def test_each_item_is_its_count_per_door_times_the_doors_that_cite_its_set() -> None:
    lines, notes = takeoff.hardware_lines(SETS, OPENINGS)
    by_key = {line.key: line for line in lines}

    hinges = by_key["1:01"]
    assert (hinges.qty_per_opening, hinges.qty, hinges.unit) == (3.0, 9.0, "EA")  # 3 hinges x 3 doors
    assert hinges.openings == ["101", "102"] and hinges.division == "08 71 00" and hinges.source_page == 16
    assert by_key["1:02"].qty == 3.0
    # A count nobody could read is a flag, never a 1.
    assert by_key["1:03"].qty is None and "quantity_unread" in by_key["1:03"].flags
    # What the schedule says another party supplies is an alternate.
    assert by_key["1:04"].alternate and "supplied_by_others" in by_key["1:04"].flags

    # A cited set nobody itemised, and one missing from the legend, are lines to price by hand.
    assert by_key["2:set"].flags == ["hardware_set_not_itemised"] and by_key["2:set"].qty == 1.0
    assert by_key["9:set"].flags == ["hardware_set_not_in_legend"]
    # A legend set no opening cites is said, not priced.
    assert "5:01" not in by_key and any("05" in note for note in notes)


def test_specialty_rows_are_lines_at_their_own_count() -> None:
    lines = takeoff.specialty_lines([
        {"division": "10 28", "qty": 2, "part": "B-5806", "manufacturer": "Bobrick", "room": "Restroom 1"},
        {"division": "10 28", "qty": 1, "part": "B-5806", "manufacturer": "Bobrick"},
        {"division": "06 64", "qty": None, "manufacturer": "Marlite", "description": "FRP panel"},
        {"division": "10 28", "qty": 1, "part": "2", "notes": "Owner furnished, contractor installed (OFCI)"},
    ])
    assert [line.key for line in lines] == ["10:B-5806", "10:B-5806-2", "06:3", "10:2"]
    assert lines[0].group == "Restroom 1" and lines[0].qty == 2.0
    assert lines[2].qty is None and "quantity_unread" in lines[2].flags
    assert "Owner furnished" in lines[3].alternate and "supplied_by_others" in lines[3].flags
