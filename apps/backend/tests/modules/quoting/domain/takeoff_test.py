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


@pytest.mark.parametrize(("reference", "key"), [
    ("GROUP #E1", "E1"), ("E1", "E1"), ("O1", "O1"), ("E01", "E1"), ("HW1", "1"), ("HW-1", "1"),
    ("3 (SEE A5.1)", "3"),  # the first name is the set's, not a sheet cited after it
])
def test_a_letter_led_legend_keeps_its_letter(reference, key) -> None:
    """E1 and O1 are two sets on a prototype's legend - never both set 1."""
    assert takeoff.set_key(reference) == key


def test_the_legends_own_supplier_makes_an_item_an_alternate() -> None:
    sets = [{"name": "E1", "items": [{"qty": "1", "part": "5200", "manufacturer": "Hager",
                                      "description": "CLOSER", "by_others": "the storefront supplier"}]}]
    [line], _ = takeoff.hardware_lines(sets, [{"mark": "100A", "set": "E1"}])
    assert line.alternate == "supplied by the storefront supplier per the legend"
    assert "supplied_by_others" in line.flags


DOORS = [
    {"mark": "101", "door_material": "HM", "frame_material": "HM", "width": "3'-0\"", "height": "7'-0\"",
     "door_type": "A", "rating": "90 MIN", "source_page": 21},
    {"mark": "102", "door_material": "HM", "frame_material": "HM", "width": "3'-0\"", "height": "7'-0\"",
     "door_type": "A", "rating": "1-1/2 HR", "source_page": 21},   # the same rating, written another way
    {"mark": "103", "door_material": "WD", "frame_material": "HM", "width": "3'-0\"", "height": "9'-0\"",
     "door_type": "B", "rating": None, "undecided": True},
    {"mark": "104", "door_material": "AL", "frame_material": "AL", "width": "6'-0\"", "height": "7'-0\""},  # storefront
    {"mark": "105", "door_material": None, "frame_material": None, "width": "6'-0\"", "height": "7'-0\""},
]


def test_doors_and_frames_are_one_line_per_specification_naming_their_doors() -> None:
    lines = {line.key: line for line in takeoff.door_and_frame_lines(DOORS)}

    rated = next(line for key, line in lines.items() if key.startswith("door:hollow metal") and "90 MIN" in key)
    assert (rated.qty, rated.openings, rated.division) == (2.0, ["101", "102"], "08 11 13")
    assert rated.description == "HOLLOW METAL DOOR, 3'-0\" X 7'-0\", TYPE A, 90 MIN RATED" and "fire_rated" in rated.flags
    tall = next(line for key, line in lines.items() if key.startswith("door:wood"))
    assert tall.division == "08 14 16" and {"custom_size", "scope_undecided"} <= set(tall.flags)
    assert not any("104" in line.openings for line in lines.values()), "aluminum is storefront, not CBC's"
    unread = next(line for key, line in lines.items() if key.startswith("door:material unread"))
    assert {"door_material_unread", "pair_check"} <= set(unread.flags)
    frames = [line for key, line in lines.items() if key.startswith("frame:")]
    assert all(line.group == "Frames" for line in frames) and sum(line.qty for line in frames) == 4.0


def test_an_exit_device_on_a_rated_door_must_be_fire_exit_hardware() -> None:
    sets = [{"name": "01", "items": [
        {"qty": "1", "part": "99EO", "manufacturer": "Von Duprin", "description": "RIM EXIT DEVICE"},
        {"qty": "1", "part": "4040XP", "manufacturer": "LCN", "description": "CLOSER"},
    ]}]
    rated, _ = takeoff.hardware_lines(sets, [{"mark": "101", "set": "01", "rating": "90 MIN"}])
    assert "fire_exit_hardware_required" in rated[0].flags and "fire_exit_hardware_required" not in rated[1].flags
    unrated, _ = takeoff.hardware_lines(sets, [{"mark": "101", "set": "01", "rating": "NR"}])
    assert "fire_exit_hardware_required" not in unrated[0].flags


def test_doors_in_a_bid_alternate_are_their_own_lines_and_the_base_keeps_the_rest() -> None:
    """FR-14: the base quantity and the alternate's, from the doors each covers."""
    sets = [{"name": "01", "items": [{"qty": "3", "part": "BB1279", "description": "HINGE"}]}]
    doors = [{"mark": "101", "set": "01"}, {"mark": "102", "set": "01"},
             {"mark": "120", "set": "01", "alternate_group": "Alternate 1"}]
    lines, _ = takeoff.hardware_lines(sets, doors)
    by_key = {line.key: line for line in lines}
    assert (by_key["1:01"].qty, by_key["1:01"].openings, by_key["1:01"].alternate_group) == (6.0, ["101", "102"], None)
    assert (by_key["1:01@Alternate 1"].qty, by_key["1:01@Alternate 1"].openings) == (3.0, ["120"])
    assert by_key["1:01@Alternate 1"].alternate_group == "Alternate 1"

    framed = takeoff.door_and_frame_lines([
        {"mark": "101", "door_material": "HM", "frame_material": "HM", "width": "3'-0\"", "height": "7'-0\""},
        {"mark": "120", "door_material": "HM", "frame_material": "HM", "width": "3'-0\"", "height": "7'-0\"",
         "alternate_group": "Alternate 1"},
    ])
    assert sorted((line.key.split("|")[0], line.alternate_group or "", line.qty) for line in framed) == [
        ("door:hollow metal", "", 1.0), ("door:hollow metal", "Alternate 1", 1.0),
        ("frame:hollow metal", "", 1.0), ("frame:hollow metal", "Alternate 1", 1.0),
    ]


def test_a_smoke_labeled_door_carries_its_label_and_needs_its_seals() -> None:
    """Requirements 6.1: the S label is the door's and the frame's; its set's
    gasketing is listed for smoke, and a set with none is reported."""
    sealed = [{"name": "01", "items": [{"qty": "3", "part": "BB1279", "description": "HINGE"},
                                       {"qty": "1", "part": "S88", "description": "SMOKE GASKET"}]}]
    lines, _ = takeoff.hardware_lines(sealed, [{"mark": "104", "set": "01", "smoke": True}])
    assert ["smoke_label" in line.flags for line in lines] == [False, True]

    bare = [{"name": "02", "items": [{"qty": "3", "part": "BB1279", "description": "HINGE"}]}]
    [hinge], _ = takeoff.hardware_lines(bare, [{"mark": "105", "set": "02", "smoke": True}])
    assert "smoke_gasketing_missing" in hinge.flags

    door, frame = takeoff.door_and_frame_lines([
        {"mark": "104", "door_material": "HM", "frame_material": "HM", "width": "3'-0\"", "height": "7'-0\"",
         "rating": "20", "smoke": True, "no_hose_stream": True},
    ])
    assert {"smoke_label", "no_hose_stream"} <= set(door.flags)
    assert "smoke_label" in frame.flags and "no_hose_stream" not in frame.flags


@pytest.mark.parametrize("notes,others", [
    ("EXISTING TO REMAIN", "EXISTING TO REMAIN"),
    ("Reuse existing closer", "Reuse existing"),
    ("existing to be re-used", "existing to be re-used"),
    ("Provide new; existing removed", None),
])
def test_hardware_already_on_the_door_is_not_cbcs_to_supply(notes, others) -> None:
    assert takeoff.supplied_by_others(notes) == others


@pytest.mark.parametrize("notes,others", [
    ("OFOI", "OFOI"),
    ("Furnished by the G.C.", "Furnished by the G.C"),
    ("Supplied by general contractor", "Supplied by general contractor"),
    ("Tenant furnished, contractor installed", "Tenant furnished"),
    ("Color selected by owner", None),
    ("Installed by GC", None),
    ("Furnished by GCS Industries", None),
])
def test_who_supplies_it_not_who_installs_it(notes, others) -> None:
    assert takeoff.supplied_by_others(notes) == others
