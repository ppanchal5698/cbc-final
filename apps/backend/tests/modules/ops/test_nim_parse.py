"""nemotron-parse client: tiling, the rotated-sheet clip, box mapping, pacing."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import fitz
import httpx
import pytest

from cbc.modules.ops.api import nim_parse

BALDWIN = Path(__file__).resolve().parents[5] / "bid_pdfs" / "_Full Set 25-073 Baldwin PA Revision 4 set 4-14-26.pdf"


def test_a_letter_page_is_one_tile_and_a_drawing_is_several_within_the_limit():
    assert len(nim_parse.tiles(612, 792)) == 1
    sheet = nim_parse.tiles(2592, 1728)
    assert 4 <= len(sheet) <= 12
    union = fitz.Rect(sheet[0])
    for rect in sheet:
        union |= rect
        assert rect.width * nim_parse.TILE_SCALE <= nim_parse.MAX_W + 1
        assert rect.height * nim_parse.TILE_SCALE <= nim_parse.MAX_H + 1
    assert union == fitz.Rect(0, 0, 2592, 1728)


def test_a_tile_of_a_rotated_sheet_shows_that_part_of_the_sheet():
    if not BALDWIN.is_file():
        pytest.skip("bid set not present")
    with fitz.open(BALDWIN) as doc:
        page = doc[18]
        assert page.rotation == 270
        full = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        rect = fitz.Rect(300, 200, 900, 600)
        png, scale = nim_parse.render_tile(page, rect)
        tile = fitz.Pixmap(png)
    assert tile.width == pytest.approx(rect.width * scale, abs=2)
    # Sample the tile against the same display-space point of the full render.
    mismatched = 0
    samples = 0
    for x in range(310, 890, 23):
        for y in range(210, 590, 19):
            a = full.pixel(x, y)
            b = tile.pixel(min(tile.width - 1, int((x - rect.x0) * scale)), min(tile.height - 1, int((y - rect.y0) * scale)))
            samples += 1
            mismatched += sum(abs(p - q) for p, q in zip(a, b)) > 120
    assert mismatched / samples < 0.1


def _response(blocks):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": "markdown_bbox", "arguments": json.dumps([blocks])}}]}}]}


def test_tile_boxes_map_to_page_points_and_an_overlap_read_is_kept_once():
    rect = fitz.Rect(1000, 500, 2000, 1300)
    blocks = nim_parse._blocks_from(_response([
        {"bbox": {"xmin": 0.1, "ymin": 0.5, "xmax": 0.3, "ymax": 0.55}, "text": "3 EA HINGE BB1279", "type": "Text"},
        {"bbox": {"xmin": 2, "ymin": 0, "xmax": 3, "ymax": 1}, "text": "off the image", "type": "Text"},
    ]))
    mapped = [m for b in blocks if (m := nim_parse._to_page(b, rect))]
    assert mapped == [{"type": "text", "text": "3 EA HINGE BB1279", "bbox": [1100.0, 900.0, 1300.0, 940.0]}]
    twice = mapped + [{**mapped[0], "bbox": [1101.0, 901.0, 1300.0, 941.0]}]
    assert len(nim_parse._dedupe(twice)) == 1


def test_parse_page_retries_a_429_and_returns_the_window_shape(tmp_path):
    pdf = tmp_path / "one.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "HARDWARE SET NO. 1")
        doc.save(pdf)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=_response([
            {"bbox": {"xmin": 0.1, "ymin": 0.08, "xmax": 0.5, "ymax": 0.1}, "text": "HARDWARE SET NO. 1", "type": "Section-header"},
        ]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await nim_parse.parse_page(client, api_key="k", pdf_path=pdf, page_number=1)

    window = asyncio.run(run())
    assert len(calls) == 2
    assert calls[1]["tools"] == [{"type": "function", "function": {"name": "markdown_bbox"}}]
    assert window["page"] == 1 and window["width"] == 612
    assert window["items"][0]["type"] == "section-header"
    assert window["items"][0]["bbox"][0] == pytest.approx(61.2)


def test_the_pacer_holds_the_call_over_the_limit():
    async def run():
        gate = nim_parse.Pacer(limit=3, window=0.4)
        start = time.monotonic()
        for _ in range(4):
            await gate.wait()
        return time.monotonic() - start

    assert asyncio.run(run()) >= 0.35
