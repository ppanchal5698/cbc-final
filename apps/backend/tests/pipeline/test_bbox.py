"""Bounding-box provenance tests.

The review screen shows the estimator the real PDF page with a highlight over the
spot a value was read from. That only works if extraction persists coordinates,
so these tests guard the contract the viewer depends on.
"""
from __future__ import annotations

import parse_schedule
from tests.shared import ROOT, SCHEDULE_PAGE

from _runtime import load_server  # noqa: E402

FIXTURE_PAGE_SIZE = {"width": 2592.0, "height": 1728.0}


def _valid_box(box) -> bool:
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(isinstance(v, (int, float)) for v in box)
        and box[2] > box[0]
        and box[3] > box[1]
    )


def test_every_opening_carries_a_bbox_and_page_size(fixture_pdf):
    openings = parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE)
    assert openings, "no openings extracted"
    for opening in openings:
        assert _valid_box(opening["bbox"]), f"bad bbox: {opening['bbox']}"
        assert opening["page_size"] == FIXTURE_PAGE_SIZE
        assert opening["cell_boxes"], "cell boxes are needed to tighten the highlight"


def test_bbox_sits_inside_the_page(fixture_pdf):
    size = parse_schedule.page_size(str(fixture_pdf), SCHEDULE_PAGE)
    for opening in parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE):
        x0, y0, x1, y1 = opening["bbox"]
        assert 0 <= x0 < x1 <= size["width"]
        assert 0 <= y0 < y1 <= size["height"]


def test_highlight_is_tightened_to_the_schedule_row(fixture_pdf):
    """A CAD sheet puts unrelated notes on the same band; the highlight must not span them.

    All four Dutch Bros rows are the same schedule columns, so a correct highlight
    is the same width on each and starts at the same x.
    """
    openings = parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE)
    widths = [round(o["bbox"][2] - o["bbox"][0], 1) for o in openings]
    lefts = [o["bbox"][0] for o in openings]
    assert len(set(widths)) == 1, f"inconsistent highlight widths: {widths}"
    assert len(set(lefts)) == 1, f"inconsistent highlight left edges: {lefts}"
    assert widths[0] < 400, "highlight is spanning unrelated sheet text"

    for opening in openings:
        raw = opening["row_bbox"]
        assert opening["bbox"][2] - opening["bbox"][0] <= raw[2] - raw[0]


def test_rows_are_vertically_ordered_and_do_not_overlap(fixture_pdf):
    boxes = [o["bbox"] for o in parse_schedule.schedule_rows(str(fixture_pdf), SCHEDULE_PAGE)]
    for upper, lower in zip(boxes, boxes[1:]):
        assert lower[1] >= upper[3] - 1, "schedule rows should stack, not overlap"


def test_pdf_tools_reports_page_size_and_row_boxes(fixture_pdf):
    pdf_tools = load_server("pdf-tools")

    size = pdf_tools.get_page_size(str(fixture_pdf), SCHEDULE_PAGE)
    assert size["width"] == FIXTURE_PAGE_SIZE["width"]
    assert size["height"] == FIXTURE_PAGE_SIZE["height"]
    assert size["page_count"] == 30

    page = pdf_tools.extract_tables(str(fixture_pdf), str(SCHEDULE_PAGE))["pages"][0]
    assert page["page_size"] == FIXTURE_PAGE_SIZE
    for row in page["rows"]:
        assert _valid_box(row["bbox"])
        assert len(row["cells"]) == len(row["cell_boxes"])
        assert "text" not in row


def test_page_size_rejects_a_page_out_of_range(fixture_pdf):
    import pytest

    with pytest.raises(ValueError):
        load_server("pdf-tools").get_page_size(str(fixture_pdf), 999)


def _rotated_page(tmp_path, rotation: int):
    """A landscape sheet with two words on one visual line, as drawings are drawn."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Same baseline, different x - one row to any human looking at the page.
    page.insert_text((72, 300), "DOOR", fontsize=11)
    page.insert_text((300, 300), "101", fontsize=11)
    # Low on the tall mediabox: past the short edge of the rotated frame, so an
    # untransformed bbox is provably outside the page rather than merely wrong.
    page.insert_text((72, 700), "SILL", fontsize=11)
    page.set_rotation(rotation)
    path = tmp_path / f"rot{rotation}.pdf"
    doc.save(path)
    doc.close()
    return path


def test_bboxes_are_in_the_frame_the_page_is_drawn_in(tmp_path):
    """A bbox has to land on the row it came from, on a rotated sheet too.

    `get_text("words")` reports against the unrotated mediabox while `page.rect`,
    the rendered image and the viewer all use the rotated frame. On a 270-rotated
    sheet those are transposed, so a highlight drawn from a raw bbox lands
    somewhere else entirely - which is what the estimator saw.

    72 of the 87 pages in the first real bid set are rotated 270.
    """
    import fitz

    from cbc.core.pdfrows import rows_from_words

    for rotation in (0, 90, 180, 270):
        path = _rotated_page(tmp_path, rotation)
        doc = fitz.open(path)
        page = doc[0]
        rows = rows_from_words(page)
        assert rows, f"rotation {rotation}: no rows"
        for row in rows:
            assert fitz.Rect(row["bbox"]) in page.rect, (
                f"rotation {rotation}: bbox {row['bbox']} outside page {tuple(page.rect)}"
            )
        doc.close()


def _drawing_page(tmp_path):
    """A landscape sheet the way a CAD tool writes one.

    Text is drawn rotated 90 in mediabox space so that it reads horizontally once
    the page's own 270 rotation is applied - which is exactly how the 72 rotated
    pages of the first real bid set are built.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((300, 200), "DOOR", fontsize=11, rotate=90)
    page.insert_text((300, 400), "101", fontsize=11, rotate=90)
    page.set_rotation(270)
    path = tmp_path / "drawing.pdf"
    doc.save(path)
    doc.close()
    return path


def test_a_row_is_grouped_as_it_appears_on_screen(tmp_path):
    """Clustering is by y, and on a 270-rotated page raw y runs along screen x.

    Before the display-space transform these two words fell in different buckets:
    the buckets were columns wearing the word "row", and a schedule read off such
    a page came out scrambled. They are one line to anyone looking at the sheet.
    """
    import fitz

    from cbc.core.pdfrows import rows_from_words

    doc = fitz.open(_drawing_page(tmp_path))
    rows = [" | ".join(r["cells"]) for r in rows_from_words(doc[0])]
    doc.close()
    assert any("DOOR" in t and "101" in t for t in rows), (
        f"one on-screen row split across rows -> {rows}"
    )


def _schedule_sheet(tmp_path):
    """Two schedule rows and one row that runs several doors together."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Columns are placed apart, as a schedule draws them - words closer than
    # COLUMN_GAP cluster into one cell and the door number stops being cell 0.
    for y, fields in (
        (200, ["1", "DINING", "3'-0\"", "7'-0\"", "A"]),
        (220, ["2", "LOBBY", "6'-0\"", "7'-0\"", "B"]),
        (240, ["5", "6'-0\"", "4", "3", "WASHING", "3'-6\""]),
    ):
        for column, text in enumerate(fields):
            page.insert_text((72 + column * 60, y), text, fontsize=9)
    path = tmp_path / "schedule.pdf"
    doc.save(path)
    doc.close()
    return path


def test_a_bbox_is_measured_from_the_row_the_opening_came_from(tmp_path):
    """The extracting pass cannot carry coordinates, so they are recovered here.

    It reads schedules through `extract_text`, which has none. Told the field was
    required it produced six boxes of identical width marching down the page in
    exact 20-point steps; once those were rejected it produced six nulls. The
    rows are still on the page and the values are still in the opening.
    """
    import fitz

    from cbc.core.pdfrows import attach_measured_bboxes

    doc = fitz.open(_schedule_sheet(tmp_path))
    page = doc[0]
    openings = [
        {"door_number": "1", "room_name": "DINING", "width": "3'-0\"", "height": "7'-0\""},
        {"door_number": "2", "room_name": "LOBBY", "width": "6'-0\"", "height": "7'-0\""},
    ]
    attached, unmatched = attach_measured_bboxes(openings, page)

    assert (attached, unmatched) == (2, 0)
    for opening in openings:
        assert fitz.Rect(opening["bbox"]) in page.rect
        assert opening["page_size"] == {
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
        }
    # Different rows, so different boxes - not one shape repeated down the page.
    assert openings[0]["bbox"] != openings[1]["bbox"]
    doc.close()


def test_a_row_holding_several_doors_is_refused(tmp_path):
    """A wrong highlight is worse than none, because it looks checked.

    Door 5's row on the real sheet reads "5 | 6'-0" | 4 | 3 | WASHING | ..." -
    three openings the clustering could not separate. Its box spans nearly the
    full sheet, so highlighting it would point the estimator at three doors and
    claim to have verified one.
    """
    import fitz

    from cbc.core.pdfrows import attach_measured_bboxes

    doc = fitz.open(_schedule_sheet(tmp_path))
    openings = [
        {"door_number": "3"},
        {"door_number": "4"},
        {"door_number": "5", "width": "6'-0\"", "room_name": "WASHING"},
    ]
    attached, unmatched = attach_measured_bboxes(openings, doc[0])

    assert attached == 0, "a row carrying three door numbers must not be claimed by one"
    assert all(o.get("bbox") is None for o in openings)
    assert any("bbox_row_not_found" in o.get("flags", []) for o in openings)
    doc.close()
