"""The take-off seeded in code: what a re-parse keeps of the rows before it."""
from __future__ import annotations

from cbc.modules.extraction.infrastructure import pretakeoff


def test_a_reparse_keeps_the_estimators_doors_and_leaves_accessories_to_their_seed() -> None:
    """A confirmed door survives a re-parse that no longer reads it; a confirmed
    accessory an export wrote into the file is not carried into the door schedule,
    where it was checked as a door and failed every re-run."""
    existing = [
        {"door_number": "101", "handing": "RH", "confirmed_by": "kevin@cbc.com"},
        {"door_number": "103", "added_by_hand": True},
        {"door_number": "B-5806", "specialty": {"kind": "div10"}, "confirmed_by": "kevin@cbc.com"},
        {"door_number": "104", "handing": "LH"},
    ]
    parsed = [{"door_number": "101", "handing": "LH"}, {"door_number": "102"}, {"door_number": "104", "handing": None}]

    merged = pretakeoff._merge(parsed, existing)

    by_mark = {o["door_number"]: o for o in merged}
    assert sorted(by_mark) == ["101", "102", "103", "104"]
    assert by_mark["101"]["handing"] == "RH", "confirmed: the estimator's row, as they left it"
    assert by_mark["104"]["handing"] == "LH", "a parser null erases nothing an earlier pass read"


def _page(path: str, page: int, marks: list[str], *, candidate_only: bool = False):
    hit = {"path": path, "source_page": page}
    if candidate_only:
        hit["candidate_only"] = True
    return hit, [{"door_number": mark, "source_page": page} for mark in marks]


def test_a_schedule_over_several_sheets_is_read_whole_and_a_stray_row_is_not() -> None:
    read = [
        _page("A.pdf", 5, ["101", "102", "103"]),
        _page("A.pdf", 6, ["104", "105", "106", "101"]),          # the schedule, continued
        _page("A.pdf", 9, ["W1", "X2", "Z3"], candidate_only=True),  # a plan, by its sheet number
        _page("A.pdf", 7, ["2"]),                                  # one stray row off an elevation
        _page("B.pdf", 1, ["107", "101", "108"]),                  # an addendum, or another building
    ]

    rows = pretakeoff._schedule_rows(read)

    # The fullest sheet first; a door it shares with another sheet of the file is its row.
    assert [(r["door_number"], r["source_page"], r["source_file"]) for r in rows] == [
        ("104", 6, "A.pdf"), ("105", 6, "A.pdf"), ("106", 6, "A.pdf"), ("101", 6, "A.pdf"),
        ("102", 5, "A.pdf"), ("103", 5, "A.pdf"), ("107", 1, "B.pdf"), ("101", 1, "B.pdf"), ("108", 1, "B.pdf"),
    ]
    again = rows[7]
    assert again["duplicate_of"] == "101" and again["duplicate_reason"] == "door 101 is also on A.pdf p6"
    assert "duplicate_of" not in rows[3]


def test_a_blank_in_a_column_the_parser_found_clears_an_earlier_misreading() -> None:
    """Evernorth's door 101: an older parser read the glazing type GL-2 as the door's
    material. The material column, found by position, is blank - and the blank is
    the sheet's. The handing column was not found, so the plan's reading stays."""
    existing = [{"door_number": "101", "door_material": "GL", "handing": "RH",
                 "evidence_note": "Handing not on this schedule row - resolve from floor-plan swing"}]
    parsed = [{"door_number": "101", "door_material": None, "handing": None,
               "columns_read": ["door_material", "door_number"]}]

    merged = pretakeoff._merge(parsed, existing)[0]

    assert merged["door_material"] is None
    assert merged["handing"] == "RH"
    assert merged["evidence_note"] is None, "a note an earlier parse wrote is that parse's, not the door's"


def test_a_handing_read_off_the_plan_keeps_its_flag_through_a_re_parse() -> None:
    existing = [{"door_number": "119", "handing": "RH", "flags": ["handing_read_from_plan", "finish_missing"]}]
    parsed = [{"door_number": "119", "handing": None, "flags": ["fire_rating_missing", "finish_missing"]}]

    merged = pretakeoff._merge(parsed, existing)[0]

    assert merged["handing"] == "RH" and "handing_read_from_plan" in merged["flags"]
    assert "fire_rating_missing" in merged["flags"], "the parse's own flags still win"
