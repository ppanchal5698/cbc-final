"""LlamaParse client: window payload, error split, and the traps we measured.

Shapes here are taken from a real job run against page 19 of the Baldwin set on
2026-09-23 - a 270-rotated CAD sheet, page.rect 2448x1584 - not invented.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from cbc.modules.ops.api import llamaparse


API = "https://api.cloud.llamaindex.ai"

# One grounded item, exactly as the sidecar delivers it: the item's own bBox is
# a huge low-confidence claim, while the grounding lines are tight and real.
GROUNDED_ITEM = {
    "type": "heading",
    "md": "# snpdesign ARCHITECTS",
    "bbox": [{"x": 740.16, "y": 218.79, "w": 805.53, "h": 1322.45, "confidence": 0.4}],
    "grounding": {
        "source": "md",
        "lines": [
            {
                "span": [2, 11],
                "bbox": {"x": 1000.0, "y": 220.0, "w": 60.0, "h": 8.0},
                "words": [{"span": [2, 11], "bbox": {"x": 1000.0, "y": 220.0, "w": 60.0, "h": 8.0}}],
            },
            {
                "span": [12, 22],
                "bbox": {"x": 1000.0, "y": 232.0, "w": 80.0, "h": 8.0},
                "words": [],
            },
        ],
    },
}

TABLE_ITEM = {
    "type": "table",
    "md": "| DOOR NO. | ROOM NAME |",
    "bbox": [{"x": 77.82, "y": 15.92, "w": 2335.99, "h": 1525.36}],
    "grounding": {
        "row_bboxes": [{"x": 717.2, "y": 1186.97, "w": 1230.32, "h": 7.21}],
        "rows": [
            [
                {"span": [0, 4], "bbox": [{"x": 1134.85, "y": 1187.15, "w": 15.45, "h": 6.85}]},
                {"span": [0, 10], "bbox": [{"x": 1052.86, "y": 1186.97, "w": 49.32, "h": 7.21}]},
            ]
        ],
    },
}


def _row(page_number: int, items: list[dict]) -> dict:
    return {
        "page_number": page_number,  # absolute AND 1-based on v2 - measured
        "page_width": 2448,
        "page_height": 1584,
        "success": True,
        "items": items,
    }


def _transport(handler):
    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# Block shaping
# --------------------------------------------------------------------------

def test_block_box_comes_from_grounding_not_the_item_bbox():
    """The item's own bBox is the region considered, not the content's bounds.

    Measured on the real sheet: this heading claimed 806x1322 of a 2448x1584 page
    at confidence 0.4 for two words. An estimator clicking that is shown a third
    of the drawing, which is not evidence. The union of the grounding lines is.
    """
    blocks = llamaparse._blocks(GROUNDED_ITEM)
    assert len(blocks) == 1, "these two lines are adjacent and stay one block"
    block = blocks[0]
    assert block["bbox"] == [1000.0, 220.0, 1080.0, 240.0]
    # Nowhere near the item's own claim.
    assert block["bbox"] != [740.16, 218.79, 1545.69, 1541.24]
    assert block["type"] == "title"  # heading -> the existing vocabulary
    assert [ln["text"] for ln in block["lines"]] == ["snpdesign", "ARCHITECTS"]


def test_table_cells_are_kept_for_per_field_evidence():
    """Cell boxes are the thing an estimator actually clicks."""
    blocks = llamaparse._blocks(TABLE_ITEM)
    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "table"
    assert block["cells"] == [
        [1134.85, 1187.15, 1150.3, 1194.0],
        [1052.86, 1186.97, 1102.18, 1194.18],
    ]
    # Box spans the cells, not the parser's page-sized table claim.
    assert block["bbox"] == [1052.86, 1186.97, 1150.3, 1194.18]


def test_item_without_grounding_is_dropped():
    """No grounding means no rectangle, and a value we cannot point at is not stored."""
    assert llamaparse._blocks(
        {"type": "text", "md": "inferred", "bbox": [{"x": 1, "y": 1, "w": 9, "h": 9}]}
    ) == []


def test_scattered_lines_split_instead_of_spanning_the_sheet():
    """LlamaParse groups by reading order, so one item can span the drawing.

    Measured on the real door-schedule sheet: a `heading` item carried lines at
    y = 222, 250, 285 and 1526. Unioning those produced a box covering 27% of the
    page - no more use as evidence than the item's own bBox, and it is what held
    verify_page at 0.48. Contiguous runs become separate blocks with tight boxes.
    """
    item = {
        "type": "text",
        "md": "alpha beta gamma faraway",
        "grounding": {
            "lines": [
                {"span": [0, 5], "bbox": {"x": 100.0, "y": 220.0, "w": 40.0, "h": 8.0}},
                {"span": [6, 10], "bbox": {"x": 100.0, "y": 232.0, "w": 40.0, "h": 8.0}},
                # 1300pt down the sheet - a different part of the drawing entirely
                {"span": [16, 23], "bbox": {"x": 100.0, "y": 1526.0, "w": 60.0, "h": 8.0}},
            ]
        },
    }
    blocks = llamaparse._blocks(item)
    assert len(blocks) == 2, "the far line must not be unioned into the paragraph"
    assert blocks[0]["bbox"] == [100.0, 220.0, 140.0, 240.0]
    assert blocks[1]["bbox"] == [100.0, 1526.0, 160.0, 1534.0]
    # Neither box spans the sheet.
    for b in blocks:
        assert (b["bbox"][3] - b["bbox"][1]) < 100


def test_degenerate_box_is_rejected():
    assert llamaparse._box({"x": 1, "y": 1, "w": 0, "h": 5}) is None
    assert llamaparse._box({"x": 1, "y": 1}) is None
    assert llamaparse._box(None) is None
    assert llamaparse._box({"x": 1, "y": 2, "w": 3, "h": 4}) == [1.0, 2.0, 4.0, 6.0]


def test_page_number_passes_through_unchanged():
    """v2 sidecar page_number is 1-based and absolute, so nothing is added.

    The v1 endpoint is 0-based, and carrying that convention across cost a real
    run: the request sent page 0 (rejected outright) and the matching `+ 1` on
    the way back would have filed every block one sheet off, which nothing
    downstream could have caught.
    """
    page = llamaparse._page(_row(19, [GROUNDED_ITEM]))
    assert page["page"] == 19
    assert (page["width"], page["height"]) == (2448.0, 1584.0)


def test_failed_page_row_is_skipped():
    assert llamaparse._page({"page_number": 4, "success": False}) is None


# --------------------------------------------------------------------------
# Transport behaviour
# --------------------------------------------------------------------------

def test_bad_key_is_permanent_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Not authenticated"})

    async def go():
        async with httpx.AsyncClient(transport=_transport(handler)) as client:
            with pytest.raises(llamaparse.ParsePermanent):
                await llamaparse.upload(client, api_key="bad", path=__file__)

    _run(go())


def test_server_error_is_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    async def go():
        async with httpx.AsyncClient(transport=_transport(handler)) as client:
            with pytest.raises(llamaparse.ParseRetryable):
                await llamaparse.upload(client, api_key="k", path=__file__)

    _run(go())


def test_fast_tier_is_refused_because_it_has_no_boxes():
    async def go():
        async with httpx.AsyncClient(transport=_transport(lambda r: httpx.Response(200))) as client:
            with pytest.raises(llamaparse.ParsePermanent) as err:
                await llamaparse.parse_window(
                    client, api_key="k", file_id="f", start_page=1, end_page=1, tier="fast"
                )
    _run(go())


def _job_handler(*, rows: list[dict] | None, status: str = "COMPLETED",
                 grounded: bool = True, seen: dict | None = None):
    sidecar = "\n".join(json.dumps(r) for r in (rows or []))

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.endswith("/api/v2/parse"):
            if seen is not None:
                seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"id": "job-1"})
        if "expand=items_content_metadata" in url:
            meta = {"items": {"presigned_url": "https://s3.test/items"}}
            if grounded:
                meta["grounded_items"] = {"presigned_url": "https://s3.test/grounded",
                                          "exists": True}
            return httpx.Response(200, json={"result_content_metadata": meta})
        if url.startswith("https://s3.test/grounded"):
            return httpx.Response(200, text=sidecar)
        if "/api/v2/parse/job-1" in url:
            return httpx.Response(200, json={"job": {"status": status}})
        return httpx.Response(404, text=url)

    return handler


def test_window_request_is_one_based_and_comma_separated():
    """A page 0 in this request is rejected by the API outright.

    Regression guard: an earlier version subtracted 1 here, carried over from the
    v1 endpoint, and every parse died on "Page numbers must be positive".
    """
    seen: dict = {}

    async def go():
        async with httpx.AsyncClient(
            transport=_transport(_job_handler(rows=[_row(5, [GROUNDED_ITEM])], seen=seen))
        ) as client:
            await llamaparse.parse_window(
                client, api_key="k", file_id="f", start_page=5, end_page=7
            )

    _run(go())
    assert seen["body"]["page_ranges"]["target_pages"] == "5,6,7"
    assert "0" not in seen["body"]["page_ranges"]["target_pages"].split(",")
    assert seen["body"]["output_options"]["granular_bboxes"] == ["word", "line", "cell"]


def test_missing_page_becomes_an_empty_row_not_a_gap():
    """A requested page the parser skipped is recorded, not dropped.

    Dropping it makes the resume count lie and the sheet disappears from the
    document instead of being routed to a visual read.
    """
    async def go():
        async with httpx.AsyncClient(
            transport=_transport(_job_handler(rows=[_row(1, [GROUNDED_ITEM])]))
        ) as client:
            return await llamaparse.parse_window(
                client, api_key="k", file_id="f", start_page=1, end_page=3
            )

    pages = _run(go())
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert pages[0]["items"] and pages[1]["items"] == [] and pages[2]["items"] == []


def test_page_outside_the_window_is_permanent():
    async def go():
        async with httpx.AsyncClient(
            transport=_transport(_job_handler(rows=[_row(41, [GROUNDED_ITEM])]))
        ) as client:
            with pytest.raises(llamaparse.ParsePermanent):
                await llamaparse.parse_window(
                    client, api_key="k", file_id="f", start_page=1, end_page=2
                )

    _run(go())


def test_no_grounded_sidecar_is_retryable_never_a_silent_empty_page():
    async def go():
        async with httpx.AsyncClient(
            transport=_transport(_job_handler(rows=[_row(1, [])], grounded=False))
        ) as client:
            with pytest.raises(llamaparse.ParseRetryable):
                await llamaparse.parse_window(
                    client, api_key="k", file_id="f", start_page=1, end_page=1
                )

    _run(go())


def test_failed_job_is_retryable():
    async def go():
        async with httpx.AsyncClient(
            transport=_transport(_job_handler(rows=None, status="FAILED"))
        ) as client:
            with pytest.raises(llamaparse.ParseRetryable):
                await llamaparse.parse_window(
                    client, api_key="k", file_id="f", start_page=1, end_page=1
                )

    _run(go())


def test_cancelled_mid_poll_stops_immediately():
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 1

    async def go():
        async with httpx.AsyncClient(
            transport=_transport(_job_handler(rows=None, status="PENDING"))
        ) as client:
            with pytest.raises(llamaparse.ParsePermanent) as err:
                await llamaparse.parse_window(
                    client, api_key="k", file_id="f", start_page=1, end_page=1,
                    cancelled=cancelled,
                )
            assert "cancelled" in str(err.value)

    _run(go())
