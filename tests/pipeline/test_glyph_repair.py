"""Recovering text from CAD exports whose fonts carry no usable ToUnicode map.

On the first real bid set, `page.get_text()` returned glyph codes rather than
characters - "DO NOT SCALE DRAWINGS" came out as "'2\x03127\x036&$/(". Nothing
noticed, so the model rediscovered the offset by hand one Bash call at a time and
still never got a clean schedule out of it.

The two things that matter here are opposites, and both are tested:

  * a mis-encoded document is repaired
  * a sound document is left completely alone
"""
from __future__ import annotations

import pytest

from tests.shared import ROOT  # noqa: E402

from _runtime import load_server  # noqa: E402

pdf = load_server("pdf-tools")

SOUND = ROOT / "tests" / "fixtures" / "pdfs" / "1_Architectural.pdf"
MIS_ENCODED = ROOT / "tests" / "fixtures" / "pdfs" / "Bid Set .pdf"

needs_sound = pytest.mark.skipif(not SOUND.exists(), reason="fixture not present")
needs_broken = pytest.mark.skipif(not MIS_ENCODED.exists(), reason="fixture not present")


# ── detection ───────────────────────────────────────────────────────────────


@needs_sound
def test_a_sound_document_is_not_touched():
    """The repair must never fire on a PDF that reads correctly already."""
    result = pdf.extract_text(str(SOUND), pages=[1])

    assert result["encoding_repaired"] is False
    assert result["encoding_shift"] == 0
    assert "DOOR SCHEDULE" in result["pages"][0]["text"]


@needs_broken
def test_a_mis_encoded_document_is_repaired_and_says_so():
    """Silently transforming a drawing value is what NFR-2 exists to prevent."""
    result = pdf.extract_text(str(MIS_ENCODED), pages="1")

    assert result["encoding_repaired"] is True
    assert result["encoding_shift"] == 29
    assert "no usable ToUnicode map" in result["encoding_note"]
    assert "DO NOT SCALE DRAWINGS" in result["pages"][0]["text"]


@needs_broken
def test_the_layout_survives_the_repair():
    """Newlines are structure, not glyph codes.

    A newline is 10, and 10 + 29 is an apostrophe - so shifting it welds every
    line of the sheet into one and destroys the rows the schedule parser reads.
    """
    text = pdf.extract_text(str(MIS_ENCODED), pages="1")["pages"][0]["text"]

    assert "\n" in text
    assert text.count("\n") > 10
    assert "DRAWINGS.\nUSE" not in text  # lines not welded together


# ── the entry points that feed the pipeline ─────────────────────────────────


@needs_broken
def test_search_reads_the_repaired_text():
    """Searching raw glyph codes reports a sheet as absent rather than unreadable."""
    hits = pdf.search_pdf(str(MIS_ENCODED), "DOOR")

    assert hits["hit_count"] > 0
    assert all(h["source_page"] >= 1 for h in hits["hits"])


@needs_broken
def test_table_rows_carry_repaired_words():
    """extract_tables clusters positioned words, which are glyph-coded too."""
    tables = pdf.extract_tables(str(MIS_ENCODED), page_range="1")

    assert tables["encoding_repaired"] is True
    joined = " ".join(
        cell for page in tables["pages"] for row in page["rows"] for cell in row["cells"]
    ).upper()
    # Words off the real sheet, not glyph codes.
    assert "COVINGTON" in joined
    assert "CONSTRUCTION" in joined


def test_a_page_that_had_to_be_cut_short_says_so():
    """Silently returning fewer rows would drop openings out of a quote."""
    tables = pdf.extract_tables(str(MIS_ENCODED), page_range="1")
    page = tables["pages"][0]

    if page["rows_truncated"]:
        assert page["row_count_on_page"] > page["row_count"]
        assert "of" in page["rows_note"]
    else:
        assert page["row_count_on_page"] == page["row_count"]


@needs_sound
def test_page_selection_accepts_a_range_string():
    """`pages="6"` raised a TypeError, which is the obvious thing to pass."""
    by_string = pdf.extract_text(str(SOUND), pages="1")
    by_list = pdf.extract_text(str(SOUND), pages=[1])

    assert by_string["pages"][0]["source_page"] == 1
    assert by_string["pages"][0]["text"] == by_list["pages"][0]["text"]
