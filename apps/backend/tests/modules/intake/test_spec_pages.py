"""A spec book's pages for the cloud reader: the sections CBC quotes, read off its own text."""
from __future__ import annotations

from cbc.modules.intake.features.ParseDocument import pages_for_the_reader

BOOK = [
    "TABLE OF CONTENTS\nDIVISION 08 - OPENINGS",                      # 1
    "SECTION 01 23 00 - ALTERNATES",                                  # 2
    "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE",                      # 3
    "SECTION 066400 - PLASTIC PANELING\nFRP panels",                  # 4
    "SECTION 087100 - DOOR HARDWARE\nHardware sets",                   # 5
    "DOOR HARDWARE 087100 - 7",                                        # 6
    "SECTION 23 05 00 - COMMON WORK RESULTS FOR HVAC",                 # 7
    "SECTION 102113.13 - METAL TOILET COMPARTMENTS",                   # 8
    "SECTION 26 05 19 - CONDUCTORS",                                   # 9
]


def test_a_spec_book_sends_only_the_sections_cbc_quotes() -> None:
    assert pages_for_the_reader(BOOK, "spec") == {1, 2, 4, 5, 6, 8}


def test_a_plan_set_or_a_scanned_book_goes_to_the_reader_whole() -> None:
    assert pages_for_the_reader(BOOK, "plan") is None
    assert pages_for_the_reader(["", "", "", "SECTION 087100"], "spec") is None, "mostly scanned"
    assert pages_for_the_reader(["SECTION 03 30 00", "SECTION 23 05 00"], "spec") is None, "none of ours: every page"
