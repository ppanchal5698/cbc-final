"""Division 10 and FRP rows get measured evidence, or an honest null.

A specialty row used to be traceable only to a page number. NFR-3 does not
accept that from an opening and it should not have accepted it from an
accessory: a page number names a sheet the estimator still has to search by eye.

The rule that matters here is the one the door path already lives by - **never
invent a box**. On the first real bid set this measures 4 of 10 Div 10 items;
three of the six it refuses cite a page their model does not appear on at all.
Surfacing that is the feature. A plausible rectangle over the wrong row is worse
than no rectangle, because it looks checked.
"""
from __future__ import annotations

import fitz
import pytest

from cbc.shared.pdfrows import attach_specialty_bboxes


@pytest.fixture
def accessory_sheet(tmp_path):
    """A two-row accessory schedule, plus a decoy row sharing one model."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "B-165-1836 1 EA MIRROR BOBRICK")
    page.insert_text((72, 140), "3741 1 EA SOAP DISPENSER KAY")
    page.insert_text((72, 180), "3741 2 EA SOAP DISPENSER KAY")
    path = tmp_path / "accessories.pdf"
    doc.save(path)
    doc.close()
    return path


def _page(path):
    doc = fitz.open(path)
    try:
        yield doc[0]
    finally:
        doc.close()


def test_a_model_on_exactly_one_row_is_measured(accessory_sheet):
    doc = fitz.open(accessory_sheet)
    items = [{"specified_model": "B-165-1836", "manufacturer": "Bobrick", "qty": 1}]

    attached, unmatched = attach_specialty_bboxes(items, doc[0], overwrite=True)
    doc.close()

    assert (attached, unmatched) == (1, 0)
    box = items[0]["bbox"]
    assert isinstance(box, list) and len(box) == 4
    assert box[2] > box[0] and box[3] > box[1]
    # Measured against the frame the viewer scales to, not the mediabox.
    assert items[0]["page_size"] == {"width": 612.0, "height": 792.0}
    assert items[0]["cell_boxes"], "cell boxes tighten the highlight"
    # And it lands on the row it claims, not somewhere plausible. `insert_text`
    # puts the baseline at y=100, so the box brackets it and stops short of the
    # next row at y=140.
    assert box[1] < 100 < box[3] < 130


def test_a_model_on_two_rows_is_refused_not_guessed(accessory_sheet):
    """Two soap dispensers, two rows, nothing to tell them apart.

    Picking either would be the invented highlight this module exists to refuse.
    """
    doc = fitz.open(accessory_sheet)
    items = [{"specified_model": "3741", "manufacturer": "Kay"}]

    attached, unmatched = attach_specialty_bboxes(items, doc[0], overwrite=True)
    doc.close()

    assert (attached, unmatched) == (0, 1)
    assert items[0]["bbox"] is None
    assert "bbox_row_ambiguous" in items[0]["flags"]


def test_a_model_that_is_not_on_the_page_says_so(accessory_sheet):
    """Three real items cited a page their model was nowhere on.

    That is an extraction fault worth seeing, and it was invisible while these
    rows carried a page number and nothing else.
    """
    doc = fitz.open(accessory_sheet)
    items = [{"specified_model": "B6800X48", "manufacturer": "Bobrick"}]

    attached, unmatched = attach_specialty_bboxes(items, doc[0], overwrite=True)
    doc.close()

    assert (attached, unmatched) == (0, 1)
    assert items[0]["bbox"] is None
    assert "bbox_row_not_found" in items[0]["flags"]


def test_overwrite_clears_a_box_the_pass_invented(accessory_sheet):
    """The pass must not be able to smuggle a rectangle past the measurement."""
    doc = fitz.open(accessory_sheet)
    items = [{
        "specified_model": "3741",
        "bbox": [10.0, 10.0, 20.0, 20.0],
        "flags": ["bbox_row_not_found", "keep_me"],
    }]

    attach_specialty_bboxes(items, doc[0], overwrite=True)
    doc.close()

    assert items[0]["bbox"] is None, "an invented box survived measurement"
    assert "keep_me" in items[0]["flags"], "unrelated flags must not be dropped"


def test_a_row_with_nothing_to_match_on_is_not_forced(accessory_sheet):
    """`product_type: accessory` describes everything, so it identifies nothing."""
    doc = fitz.open(accessory_sheet)
    items = [{"product_type": "accessory", "qty": 1}]

    attached, unmatched = attach_specialty_bboxes(items, doc[0], overwrite=True)
    doc.close()

    assert (attached, unmatched) == (0, 1)
    assert items[0]["bbox"] is None
