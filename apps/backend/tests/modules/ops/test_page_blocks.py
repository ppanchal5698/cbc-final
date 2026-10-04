"""Normaliser: frame, rotation, page numbering and the bbox requirement.

The rotated-page cases are the ones that matter. 72 of the 87 pages in the first
real bid set are rotated 270, and a bbox in the wrong frame lands nowhere near
its row while still passing every shape check.
"""
from __future__ import annotations

from pathlib import Path

import fitz

from cbc.modules.ops.api import page_blocks

PARSER = {"name": "llamaparse", "tier": "cost_effective"}


def _pdf(tmp_path: Path, *, rotation: int, text: str = "DOOR SCHEDULE") -> Path:
    path = tmp_path / f"rot{rotation}.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), text, fontsize=14)
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()
    return path


def _window(page: int, blocks: list[dict], width: float, height: float) -> list[dict]:
    return [{"page": page, "width": width, "height": height, "items": blocks}]


def test_page_size_is_the_display_rect_not_the_parser_claim(tmp_path: Path):
    """pageSize always comes from page.rect, so a parser swap moves nothing."""
    pdf = _pdf(tmp_path, rotation=270)
    check = fitz.open(pdf)
    display = check[0].rect
    check.close()
    assert (round(display.width), round(display.height)) == (792, 612)

    rows = page_blocks.normalise_window(
        # Parser lies about the size; we ignore it.
        _window(1, [{"type": "text", "text": "x", "bbox": [10, 10, 60, 30]}], 1.0, 1.0),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["pageSize"] == {"width": round(display.width, 2),
                                   "height": round(display.height, 2)}


def test_display_frame_parser_is_left_alone_on_a_270_page(tmp_path: Path):
    """LlamaParse reports display space; mapping it would push boxes off the page."""
    pdf = _pdf(tmp_path, rotation=270)
    check = fitz.open(pdf)
    w, h = check[0].rect.width, check[0].rect.height
    check.close()

    claim = [100.0, 50.0, 200.0, 70.0]
    rows = page_blocks.normalise_window(
        _window(1, [{"type": "text", "text": "TITLE", "bbox": list(claim)}], w, h),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["blocks"][0]["bbox"] == claim, "display-space box must not be remapped"


def test_unrotated_frame_parser_is_mapped_on_a_270_page(tmp_path: Path):
    """A parser reporting the mediabox still gets the rotation matrix."""
    pdf = _pdf(tmp_path, rotation=270)
    check = fitz.open(pdf)
    page = check[0]
    claim = [72.0, 60.0, 200.0, 90.0]
    mapped = (fitz.Rect(claim) * page.rotation_matrix).normalize()
    expected = [round(v, 2) for v in (mapped.x0, mapped.y0, mapped.x1, mapped.y1)]
    check.close()

    rows = page_blocks.normalise_window(
        # 612x792 is the unrotated mediabox - transposed against page.rect.
        _window(1, [{"type": "text", "text": "TITLE", "bbox": list(claim)}], 612, 792),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["blocks"][0]["bbox"] == expected


def test_180_rotation_is_settled_by_coverage_not_size(tmp_path: Path):
    """At 180 both frames are the same size, so size cannot decide.

    `_needs_rotation` returns False on every 180 page - the sizes always match -
    while the transform (x,y) -> (W-x, H-y) is real. Left to size alone, every box
    is stored point-mirrored under a page_size that looks correct.
    """
    pdf = _pdf(tmp_path, rotation=180)
    check = fitz.open(pdf)
    page = check[0]
    claim = [70.0, 88.0, 220.0, 104.0]
    mapped = (fitz.Rect(claim) * page.rotation_matrix).normalize()
    expected = [round(v, 2) for v in (mapped.x0, mapped.y0, mapped.x1, mapped.y1)]
    assert page_blocks._needs_rotation((612.0, 792.0), page) is False  # the defect
    assert page_blocks._rotation_is_ambiguous(page) is True
    check.close()

    rows = page_blocks.normalise_window(
        _window(1, [{"type": "text", "text": "DOOR SCHEDULE", "bbox": list(claim)}],
                612, 792),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["blocks"][0]["bbox"] == expected
    assert rows[0]["verified"] == 1.0


def test_page_number_is_taken_from_the_payload_not_position(tmp_path: Path):
    """No enumeration offset: a skipped page cannot shift every later one."""
    pdf = _pdf(tmp_path, rotation=0)
    doc = fitz.open(pdf)
    doc.new_page(width=612, height=792)
    doc.new_page(width=612, height=792)
    two = tmp_path / "three.pdf"
    doc.save(two)
    doc.close()

    window = [
        {"page": 1, "width": 612, "height": 792,
         "items": [{"type": "text", "text": "a", "bbox": [10, 10, 40, 20]}]},
        # page 2 missing entirely - page 3 must still be filed as 3
        {"page": 3, "width": 612, "height": 792,
         "items": [{"type": "text", "text": "c", "bbox": [10, 10, 40, 20]}]},
    ]
    rows = page_blocks.normalise_window(
        window, pdf_path=two, project_id="p", document_id="d",
        content_sha="s", parser=PARSER,
    )
    assert [r["page"] for r in rows] == [1, 3]


def test_text_without_a_bbox_is_dropped_and_counted(tmp_path: Path):
    pdf = _pdf(tmp_path, rotation=0)
    rows = page_blocks.normalise_window(
        _window(1, [
            {"type": "text", "text": "DOOR SCHEDULE", "bbox": [70, 88, 220, 104]},
            {"type": "text", "text": "INFERRED SUMMARY"},          # no box
            {"type": "image", "text": "FIGURE 1"},                 # exempt
        ], 612, 792),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["droppedNoBbox"] == 1
    texts = [b.get("text") for b in rows[0]["blocks"]]
    assert "INFERRED SUMMARY" not in texts
    assert any(b.get("type") == "image" for b in rows[0]["blocks"])


def test_cells_are_carried_through_for_per_field_evidence(tmp_path: Path):
    """Cell boxes are what the estimator clicks; they must survive normalisation."""
    pdf = _pdf(tmp_path, rotation=0)
    rows = page_blocks.normalise_window(
        _window(1, [{
            "type": "table", "text": "| DOOR |", "bbox": [70, 80, 300, 200],
            "cells": [[70.0, 80.0, 150.0, 95.0], [150.0, 80.0, 300.0, 95.0]],
        }], 612, 792),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["blocks"][0]["cells"] == [
        [70.0, 80.0, 150.0, 95.0], [150.0, 80.0, 300.0, 95.0]
    ]


def test_cells_rotate_with_their_block(tmp_path: Path):
    """A cell box left in the old frame is a highlight on the wrong part of the sheet."""
    pdf = _pdf(tmp_path, rotation=270)
    check = fitz.open(pdf)
    page = check[0]
    cell = [72.0, 60.0, 120.0, 75.0]
    m = (fitz.Rect(cell) * page.rotation_matrix).normalize()
    expected = [round(v, 2) for v in (m.x0, m.y0, m.x1, m.y1)]
    check.close()

    rows = page_blocks.normalise_window(
        _window(1, [{"type": "table", "text": "t", "bbox": [72, 60, 200, 90],
                     "cells": [list(cell)]}], 612, 792),
        pdf_path=pdf, project_id="p", document_id="d", content_sha="s", parser=PARSER,
    )
    assert rows[0]["blocks"][0]["cells"] == [expected]
