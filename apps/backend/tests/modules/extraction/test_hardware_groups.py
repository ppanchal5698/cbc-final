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
