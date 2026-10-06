"""A spec's hardware schedule prints symbol-font markers beside its items."""
from __future__ import annotations

from cbc.modules.extraction.infrastructure import hardware_groups as hg


def test_a_symbol_font_marker_is_no_part_of_the_item() -> None:
    """Evernorth's legend: a link-to-cut-sheet glyph and an electrified-opening glyph,
    read out of the private-use area - the strike's finish came back as one."""
    item = hg.classify_item(["1", "EA", "ELECTRIC STRIKE", "8000C X 2005M3", "\uf09d \uf07e630", "HES"])
    assert item["finish"] == "630" and "\uf07e" not in (item["description"] or "")
    assert hg.classify_text_item("HES 8000C ELECTRIC STRIKE \uf07e630")["finish"] == "630"
