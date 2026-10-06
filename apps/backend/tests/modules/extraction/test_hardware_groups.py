"""The hardware legend, read deterministically.

A door schedule cites a hardware group per opening; nothing ever parsed the
legend that says what those groups contain. Two different bid sets reached
pricing with zero manufacturer parts and a row of blank MANUAL lines, and the
Hager special-net sheet could never be exercised because the parts that would
use it never left the PDF.

Same contract as the door-schedule parser: **never silently wrong**. A cell the
parser cannot classify leaves its field null, flags the item, and keeps the text
in `raw_row`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cbc.modules.extraction.infrastructure import hardware_groups as hg
from tests.shared import ROOT

WENDYS = ROOT / "bid_pdfs" / "17037_Wendys_Acheson_A_DWG_IFT.pdf"
LEGEND_PAGE = 16

# What an estimator reading page 16 by eye would write down. Groups 07, 08 and 12
# are the ones this bid's door schedule actually cites.
EXPECTED_SETS = {"01", "01A", "01B", "02", "03", "03A", "05", "07", "08", "11", "12"}


# ── row classification: no PDF needed ───────────────────────────────────────

@pytest.mark.parametrize(
    "cells,part,manufacturer,finish",
    [
        (["1", "EA. STOREROOM", "3580 26D WTN SFIC", "26D / 626", "HAGER", "GC"],
         "3580", "Hager", "26D / 626"),
        (['1 1/2 EA. HINGES', 'BB1279 4 1/2" x 4 1/2"', "US10B", "HAGER", "GC"],
         "BB1279", "Hager", "US10B"),
        (["1", "EA. EXIT DEVICE RIM", "4501-48-26D", "26D / 626", "HAGER", "LL"],
         "4501-48-26D", "Hager", "26D / 626"),
        (["1", "EA. CLOSER 5100", "5100-HDHOS-ALUM", "ALUMINUM", "HAGER", "LL"],
         "5100-HDHOS-ALUM", "Hager", "ALUMINUM"),
        (["1", "EA. HALF SADDLE", "431S-42-MIL", "MIL", "HAGER", "LL"],
         "431S-42-MIL", "Hager", "MIL"),
    ],
)
def test_a_legend_row_yields_its_part(cells, part, manufacturer, finish) -> None:
    item = hg.classify_item(cells)
    assert item["part"] == part
    assert item["manufacturer"] == manufacturer
    assert item["finish"] == finish


def test_a_numeric_part_is_not_mistaken_for_a_finish() -> None:
    """Hager writes `350` for a threshold, and `350` is also three digits.

    Reading by pattern alone handed the part number to the finish field. The
    manufacturer is the positional anchor: finish sits before it, part before
    that.
    """
    item = hg.classify_item(["1", "EA. THRESHOLD", "350", "32D", "HAGER", "LL"])
    assert item["part"] == "350"
    assert item["finish"] == "32D"


def test_the_unit_takes_its_full_stop_with_it() -> None:
    """`\\b` after `EA\\.?` left the dot heading the description as `. STOREROOM`."""
    item = hg.classify_item(["1", "EA. STOREROOM", "3580", "26D", "HAGER", "GC"])
    assert item["unit"] == "EA."
    assert not str(item["description"]).startswith(".")


def test_a_fractional_count_survives() -> None:
    item = hg.classify_item(['1 1/2 EA. HINGES', "BB1279", "US10B", "HAGER", "GC"])
    assert item["qty"] == "1 1/2"


def test_an_unknown_vendor_is_flagged_not_guessed() -> None:
    item = hg.classify_item(["1", "EA. LOCK", "XX9", "26D", "WIDGETCO", "GC"])
    assert item["manufacturer"] is None
    assert "manufacturer_missing" in item["flags"]
    assert "WIDGETCO" in item["raw_row"], "the text is kept even when unclassified"


def test_a_row_with_no_part_says_so() -> None:
    item = hg.classify_item(["3", "EA.", "US10B", "HAGER", "LL"])
    assert item["part"] is None
    assert "part_missing" in item["flags"]


# ── column banding ──────────────────────────────────────────────────────────

def test_columns_are_bounded_on_both_sides() -> None:
    """An unbounded last column swallowed the title block as hardware.

    "PROJECT NO:", "17037" and "PROVIDE LEFT HANDED OPERATION" all arrived as
    items. The legend sits at x 407-1277 on this sheet; that noise starts at 1907.
    """
    bands = [(68.0, 503.0), (503.0, 938.0), (938.0, 1373.0)]
    assert hg._band_of(70.0, bands) == 0
    assert hg._band_of(940.0, bands) == 2
    assert hg._band_of(2324.0, bands) is None


def test_no_headers_means_no_bands() -> None:
    assert hg._column_bands([]) == []


# ── one table, group names written vertically ───────────────────────────────
#
# The Dutch Bros prototype sheet (A2.2): `#: | DESCRIPTION | MFR. | MODEL & FINISH`
# with "GROUP 1 - BACK DOOR" written up a merged first column. No row holds a group
# header or a quantity, so the column reader found nothing and the bid reached
# pricing with no hardware at all. Coordinates below are the ones measured on it.

def _row(y: float, *cells: tuple[str, float]) -> dict:
    return {
        "y": y,
        "cells": [text for text, _ in cells],
        "cell_boxes": [[x, y, x + 6 * len(text), y + 9] for text, x in cells],
    }


def _vertical(x: float, bottom: float, text: str) -> list[tuple]:
    """A label written bottom to top, one box per word, as the text layer gives it."""
    words, y = [], bottom
    for word in text.split():
        height = 6 * len(word)
        words.append((x, y - height, x + 10, y, word))
        y -= height + 3
    return words


def _legend(first: list[tuple[str, str, str]], second: list[tuple[str, str, str]]) -> tuple[list, list]:
    rows = [_row(726, ("#:", 542), ("DESCRIPTION", 564), ("MFR.", 683), ("MODEL & FINISH", 786))]
    y = 753.0
    spans = []
    for group in (first, second):
        start = y
        for description, maker, model in group:
            rows.append(_row(y, (description, 564), (maker, 665), (model, 748)))
            y += 23.5
        spans.append((start + y - 23.5 + 9) / 2)
    words = _vertical(542, spans[0] + 51, "GROUP 1 - BACK DOOR")
    words += _vertical(542, spans[1] + 63, "GROUP 3 - RESTROOM DOOR")
    return rows, words


BACK_DOOR = [
    ("HINGE", "IVES", '700 83", 630'), ("DOOR CLOSER", "LCN", "4040XP RW/PA ALUM."),
    ("LOCKSET", "ALARM LOCK", "ETDL27R1G/26DV 99"), ("PANIC HARDWARE", "VON DURPIN", '99EO 42" 626'),
    ("KICK PLATE", "IVES", '8400, 40"x30", 630, AT INTERIOR'), ("THRESHOLD", "PEMKO", '275A, 42"'),
    ("DOOR SHOE", "ZERO", '39A SWEEP, 42"'), ("DOOR SEAL", "ZERO", "188S BK, 18'"),
    ("FLOOR STOP", "IVES", "FS43, 626"),
]
OFFICE_DOOR = [
    ("HINGES", "IVES", "(3) 5BB1, 4.5, NRP, 626"), ("LOCKSET", "SCHLAGE", "ND10S RHO, 626"),
    ("KICK PLATE", "IVES", '8400, 34"x12", 630'), ("FLOOR STOP", "IVES", "FS43, 626"),
]


def test_a_vertical_group_name_is_read_bottom_to_top() -> None:
    labels = hg._vertical_labels(_vertical(542, 902, "GROUP 1 - BACK DOOR"), 524, 563, 735)
    assert [(label["set_id"], label["specified"]) for label in labels] == [("1", "BACK DOOR")]


def test_a_one_table_legend_splits_into_its_groups() -> None:
    """Nine rows over four. Splitting halfway between the two labels put the first
    group's last row (the floor stop) in the second group."""
    rows, words = _legend(BACK_DOOR, OFFICE_DOOR)
    sets = hg._matrix_sets(rows, words, 15, {"width": 2592, "height": 1728})

    assert [s["set_id"] for s in sets] == ["1", "3"]
    assert [len(s["items"]) for s in sets] == [9, 4]
    assert sets[0]["items"][-1]["description"] == "FLOOR STOP"
    assert sets[1]["items"][0]["description"] == "HINGES"
    assert all(not s["flags"] for s in sets)


def test_rows_below_the_table_are_not_hardware() -> None:
    rows, words = _legend(BACK_DOOR, OFFICE_DOOR)
    rows.append(_row(1400, ("REFERENCE DOOR SCHEDULE", 564), ("FOR SIZES", 665)))
    sets = hg._matrix_sets(rows, words, 15, {"width": 2592, "height": 1728})
    assert [len(s["items"]) for s in sets] == [9, 4]


@pytest.mark.parametrize(
    "model,qty,part,finish",
    [
        ("(3) 5BB1, 4.5, NRP, 626", "3", "5BB1", "626"),
        ('700 83", 630', None, "700", "630"),
        ("4040XP RW/PA ALUM.", None, "4040XP", "ALUM."),
        ('8400, 34"x30", 630. AT INTERIOR', None, "8400", "630"),
        ("ETDL27R1G/26DV 99", None, "ETDL27R1G/26DV", None),
    ],
)
def test_a_model_cell_gives_its_part_count_and_finish(model, qty, part, finish) -> None:
    item = hg.classify_matrix_item("HINGES", "IVES", model)
    assert (item["qty"], item["part"], item["finish"]) == (qty, part, finish)


def test_the_misspelt_von_duprin_still_reaches_the_allegion_gate() -> None:
    """An unrecognised maker would let a Von Duprin device be priced off a list."""
    assert hg.classify_matrix_item("PANIC HARDWARE", "VON DURPIN", "99EO")["manufacturer"] == "Von Duprin"


# ── the real sheet ──────────────────────────────────────────────────────────

requires_wendys = pytest.mark.skipif(
    not WENDYS.is_file(), reason="Wendy's bid set is not in bid_pdfs/"
)


@pytest.fixture(scope="module")
def legend() -> dict:
    return hg.groups_on_page(WENDYS, LEGEND_PAGE)


@requires_wendys
def test_every_set_on_the_sheet_is_found(legend) -> None:
    found = {entry["hardware_set"] for entry in legend["sets"]}
    assert found == EXPECTED_SETS, f"missing {EXPECTED_SETS - found}, extra {found - EXPECTED_SETS}"


@requires_wendys
def test_the_groups_the_door_schedule_cites_have_items(legend) -> None:
    """Groups 07, 08 and 12 are what this bid's openings point at."""
    by_set = {entry["hardware_set"]: entry for entry in legend["sets"]}
    for name in ("07", "08", "12"):
        assert by_set[name]["items"], f"SET {name} came back empty"


@requires_wendys
def test_the_hager_parts_that_price_are_all_recovered(legend) -> None:
    """These nine are on CBC's special-net sheet; before this parser, none left the PDF."""
    parts = {item["part"] for entry in legend["sets"] for item in entry["items"] if item["part"]}
    for part in ("3580", "BB1279", "4501-48-26D", "5100-HDHOS-ALUM", "5200",
                 "190S-20X40-32D", "431S-42-MIL", "810S-46-MIL", "236W"):
        assert part in parts, part


@requires_wendys
def test_most_items_carry_a_part_number(legend) -> None:
    """Coverage, not perfection - but a legend that yields mostly blanks is broken."""
    items = [item for entry in legend["sets"] for item in entry["items"]]
    with_part = [item for item in items if item["part"]]
    assert len(items) >= 60, len(items)
    assert len(with_part) / len(items) >= 0.75, f"only {len(with_part)}/{len(items)}"


@requires_wendys
def test_nothing_from_the_title_block_is_read_as_hardware(legend) -> None:
    """The sheet number, project number and general notes are not hardware."""
    blob = " ".join(
        str(item.get("description") or "") + " " + str(item.get("raw_row") or "")
        for entry in legend["sets"]
        for item in entry["items"]
    ).upper()
    for stray in ("PROJECT NO", "17037", "WINDOW FRAMES", "HANDED OPERATION"):
        assert stray not in blob, stray


@requires_wendys
def test_every_set_cites_the_page_it_was_read_from(legend) -> None:
    """NFR-3: a value with no page is unauditable."""
    for entry in legend["sets"]:
        assert entry["source_page"] == LEGEND_PAGE
        assert entry["page_size"]["width"] > 0 and entry["page_size"]["height"] > 0


@requires_wendys
def test_reading_the_same_page_twice_gives_the_same_answer(legend) -> None:
    """The point of the whole exercise: a deterministic parser is deterministic."""
    again = hg.groups_on_page(WENDYS, LEGEND_PAGE)
    assert again == legend


@requires_wendys
def test_the_legend_page_is_found_without_being_told(legend) -> None:
    assert LEGEND_PAGE in hg.find_legend_pages(WENDYS)


def test_a_page_with_no_legend_says_why(tmp_path) -> None:
    """An honest empty beats an invented set."""
    import fitz

    blank = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(blank)
    doc.close()

    found = hg.groups_on_page(blank, 1)
    assert found["sets"] == []
    assert found["no_legend_reason"]


# ── the formats the corpus taught: headings, abbreviations, tables, bullets ──

@pytest.mark.parametrize("line,set_id", [
    ("HARDWARE SET: 01", "01"), ("HARDWARE GROUP NO. 02", "02"), ("HW SET 3", "3"),
    ("GROUP #E1: TYPICAL EXTERIOR VESTIBULE DOORS", "E1"), ("SET 03A – REAR SERVICE", "03A"),
])
def test_every_way_a_legend_heads_a_set(line, set_id) -> None:
    header = hg.TEXT_SET_HEADER.match(line) or hg.SET_HEADER.search(line) or hg.SET_BARE.search(line)
    assert header and header.group(1).upper() == set_id


def test_a_unit_is_a_word_not_the_start_of_one() -> None:
    """PR is not the start of PRIVACY, nor EA of EACH or EASY."""
    item = hg.classify_item(["1", "PRIVACY LOCK", "QCL240.M.626", "STANELY"])
    assert (item["unit"], item["description"], item["manufacturer"]) == (None, "PRIVACY LOCK", "Stanley")
    assert not hg._is_item_row(["EACH TO HAVE:"]) and not hg._is_item_row(["Provide each SGL door(s)"])


def test_a_schedules_maker_abbreviations_anchor_its_part_and_finish() -> None:
    item = hg.classify_item(["1", "EA", "ENTRANCE LOCK", "ND53PD SPA", "626", "SCH"])
    assert (item["manufacturer"], item["part"], item["finish"]) == ("Schlage", "ND53PD", "626")
    # ...but only as a cell of their own: in running text DET is a detail.
    assert hg.classify_text_item("SEE DET. 3 FOR CLOSER")["manufacturer"] is None


def test_a_part_shaped_like_a_finish_is_still_a_part() -> None:
    item = hg.classify_text_item('BACK TO BACK PULL: HAGER 21J 10" 32D')
    assert (item["part"], item["finish"]) == ("21J", "32D")


def test_a_legend_without_counts_means_one_each_but_never_for_butt_hinges() -> None:
    closer = {"qty": None, "description": "SURFACE CLOSER", "raw_row": "", "flags": ["qty_missing"]}
    hg.assume_one_each(closer)
    assert closer["qty"] == "1" and closer["flags"] == ["qty_assumed_one"]
    butts = {"qty": None, "description": "HINGES", "raw_row": "HAGER BB1279", "flags": []}
    hg.assume_one_each(butts)
    assert butts["qty"] is None and "hinge_count_unstated" in butts["flags"]
    continuous = {"qty": None, "description": "HINGE", "raw_row": 'IVES 700 83", 630', "flags": []}
    hg.assume_one_each(continuous)
    assert continuous["qty"] == "1"


def _header(y: float, at: float) -> dict:
    return _row(y, ("GROUP #", at), ("DOOR", at + 60), ("QTY", at + 103), ("DESCRIPTION", at + 137),
                ("CATALOG #", at + 266), ("MFG", at + 455))


def test_a_table_legend_reads_each_group_beside_the_next() -> None:
    """Two tables side by side, a header over each block, a group's number on its
    first row and its name down the column - and the text layer splitting one
    visual row in two, a maker four points above its item."""
    rows = [
        _header(1213.2, 685),
        _row(1235.3, ("7", 707), ("6", 758)), _row(1236.3, ("3", 798), ("HINGE", 821), ("MARLITE", 1149)),
        _row(1253.5, ("OFFICE", 689)),
        _header(1254.5, 137),
        _row(1254.6, ("DOOR", 704), ("1", 798), ("STOREROOM LOCK", 821), ("QCL 270.M.626", 947), ("STANELY", 1149)),
        _row(1277.6, ("5", 159), ("1, 2", 205), ("3", 250), ("HINGE", 273), ("MARLITE", 587)),
        _row(1295.4, ("BURNS", 587)),
        _row(1299.5, ("PUBLIC RESTROOM DOOR", 139), ("1", 250), ("PUSHPLATE", 273), ("#53 x US32D", 399)),
        _row(1336.3, ("1", 250), ("SURFACE CLOSER", 273), ("4011", 399), ("LCN", 587)),
        _row(1356.3, ("2", 250), ("KICK PLATE", 273), ('8" x 34" ALUM 628', 397), ("ROCKWOOD", 587),
             ("GENERAL NOTES:", 1278)),
        _row(1414.8, ("*NOTES - ARM PULL OPTIONAL", 144)),
    ]
    sets = {s["set_id"]: s for s in hg._table_sets(rows, 4, {"width": 2592, "height": 1728})}
    assert set(sets) == {"5", "7"}
    office, restroom = sets["7"], sets["5"]
    assert office["specified"] == "OFFICE DOOR" and office["doors"] == ["6"]
    assert [(i["qty"], i["manufacturer"]) for i in office["items"]] == [("3", "Marlite"), ("1", "Stanley")]
    assert restroom["specified"] == "PUBLIC RESTROOM DOOR" and restroom["doors"] == ["1", "2"]
    descriptions = [i["description"] for i in restroom["items"]]
    assert descriptions[:3] == ["HINGE", "PUSHPLATE x US32D", "SURFACE CLOSER"]
    assert descriptions[3] == 'KICK PLATE 8" x 34" ALUM 628'  # no part in the cell: its size stays with it
    assert restroom["items"][1]["manufacturer"] == "Burns" and restroom["items"][2]["part"] == "4011"
    # The general notes beside the table and the note under the group are not hardware.
    assert all("NOTES" not in (i["raw_row"] or "") for s in sets.values() for i in s["items"])


SHAKOPEE = ROOT / "bid_pdfs" / "Shakopee,_MN,_#0131_-_Reimage_Final_Drawings_-_6.12.26_pdf.pdf"
EVERNORTH_MANUAL = ROOT / "bid_pdfs" / "26136.0000 Evernorth - Accredo Elgin Project Manual 04242026.pdf"
DAIRY_QUEEN = ROOT / "bid_pdfs" / "A303" / "A202.pdf"


def _needs(pdf: Path) -> None:
    if not pdf.is_file():
        pytest.skip(f"{pdf.name} is not in bid_pdfs/")


def test_the_culvers_table_legend_is_read() -> None:
    _needs(SHAKOPEE)
    sets = {s["set_id"]: s for s in hg.groups_on_page(SHAKOPEE, 4)["sets"]}
    assert {"5", "6", "7", "8"} <= set(sets)
    assert any(i["part"] == "4011" and i["manufacturer"] == "LCN" for i in sets["5"]["items"])
    assert all(i["qty"] for s in sets.values() for i in s["items"])


def test_a_specifications_hardware_schedule_is_read() -> None:
    """`HARDWARE SET: 01` / `HARDWARE GROUP NO. 02`, makers written SCH, IVE, LCN."""
    _needs(EVERNORTH_MANUAL)
    sets = {s["set_id"]: s for page in (249, 250) for s in hg.groups_on_page(EVERNORTH_MANUAL, page)["sets"]}
    assert set(sets) == {"01", "02", "03", "04"}
    hinge = next(i for i in sets["02"]["items"] if i["part"] == "5BB1")
    assert (hinge["qty"], hinge["manufacturer"], hinge["finish"]) == ("3", "IVES", "652")
    reader = next(i for i in sets["02"]["items"] if "CREDENTIAL READER" in (i["description"] or ""))
    assert reader["supplied_by"] == "SECURITY VENDOR"


def test_a_bullet_legends_groups_counts_and_storefront_supply_are_read() -> None:
    """`GROUP #E1:` heads, `CLOSER: HAGER MFG., MODEL #5200` items, `(4) HINGES PER LEAF`
    on the wrapped line, and a note that hands a group to the storefront supplier."""
    _needs(DAIRY_QUEEN)
    sets = {s["set_id"]: s for s in hg.groups_on_page(DAIRY_QUEEN, 1)["sets"]}
    assert {"E1", "E2", "E3", "O1", "O2", "R1", "S1"} <= set(sets)
    hinges = next(i for i in sets["E1"]["items"] if i["part"] == "ECBB1199")
    assert hinges["qty"] == 4.0
    assert {i["supplied_by"] for i in sets["E1"]["items"]} == {"STOREFRONT"}
    assert all(i["supplied_by"] is None for i in sets["O2"]["items"])
    closer = next(i for i in sets["O2"]["items"] if (i["description"] or "").startswith("CLOSER"))
    assert (closer["part"], closer["qty"], closer["manufacturer"]) == ("5200", "1", "Hager")


def test_a_spec_books_schedule_pages_are_tried_before_pages_that_only_mention_hardware() -> None:
    """The map tags every page that mentions hardware; the eight it ranked first in
    the Evernorth manual were steel-door sections, and the sets on 249-250 were
    never read."""
    _needs(EVERNORTH_MANUAL)
    from cbc.modules.extraction.infrastructure import pretakeoff

    path = "bid_pdfs/" + EVERNORTH_MANUAL.name
    ranked = [{"path": path, "source_page": page} for page in (225, 218, 219, 233, 247, 223, 248, 220, 249, 250)]
    tried = pretakeoff._legend_pages_first("evernorth", ranked)
    assert [c["source_page"] for c in tried[:2]] == [249, 250]
    assert len(tried) == 2 + pretakeoff.MAX_PAGES_TRIED
