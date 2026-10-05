"""NVIDIA NIM nemotron-parse client: one page in, parser-neutral blocks out.

The same shape `llamaparse` hands over, so `page_blocks.normalise_window`, the
documentPages rows, the sheet viewer and the bid digest never know which parser
read a page.

nemotron-parse takes one image of at most 1648x2048 px and answers with a list
of blocks - `{"bbox": {xmin, ymin, xmax, ymax} in 0-1 of the image, "text",
"type"}` - through its `markdown_bbox` tool. A 36x24" drawing squeezed into
2048 px is about 0.8 px/pt and schedule text is unreadable, so a sheet is cut
into tiles at TILE_SCALE px/pt (legible) and each tile is read on its own. Boxes
come back tile-relative and are mapped to page points; a block read twice in the
overlap between two tiles is kept once.

The free tier allows 40 requests a minute and answers the 41st with 429, so
every call goes through one process-wide sliding-window pacer.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import time
from collections import deque
from pathlib import Path
from typing import Any

import fitz
import httpx

log = logging.getLogger(__name__)

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-parse"
DEFAULT_RPM = 40
PARSER = {"name": "nemotron-parse", "version": "nim", "tier": None}

MAX_W, MAX_H = 2048, 1648        # the model's limit, landscape; swapped for portrait tiles
TILE_SCALE = 2.0                 # px per pt: the readability floor pdfpages also uses
OVERLAP_PT = 48.0                # a line cut by a tile edge is whole in its neighbour
MAX_TILES = 24                   # a 48x36" sheet is 12; anything larger is not a drawing


class NimError(RuntimeError):
    """A page NIM could not deliver. The caller reads it locally instead."""


class Pacer:
    """At most `limit` calls in any rolling 60 s, shared by every caller in the process."""

    # ponytail: per process. Two workers reading NIM at once (the parser service
    # and a claim-all worker) can together exceed the limit; NVIDIA's 429 and its
    # retry-after are the backstop. Move the window into Mongo if that shows up.

    def __init__(self, limit: int = DEFAULT_RPM, window: float = 60.0) -> None:
        self.limit, self.window = max(1, limit), window
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._hits and now - self._hits[0] >= self.window:
                    self._hits.popleft()
                if len(self._hits) < self.limit:
                    self._hits.append(now)
                    return
                await asyncio.sleep(self.window - (now - self._hits[0]) + 0.05)


_pacers: dict[int, Pacer] = {}


def pacer(rpm: int = DEFAULT_RPM) -> Pacer:
    """One pacer per limit per event loop's process: the limit is NVIDIA's, per key."""
    if rpm not in _pacers:
        _pacers[rpm] = Pacer(rpm)
    return _pacers[rpm]


def tiles(width: float, height: float) -> list[fitz.Rect]:
    """Display-space rectangles covering the page, each renderable within the model's limit."""
    landscape = width >= height
    max_w, max_h = (MAX_W, MAX_H) if landscape else (MAX_H, MAX_W)
    # A page that fits whole at the readable scale is one tile.
    if width * TILE_SCALE <= max_w and height * TILE_SCALE <= max_h:
        return [fitz.Rect(0, 0, width, height)]
    tile_w, tile_h = max_w / TILE_SCALE, max_h / TILE_SCALE
    cols = max(1, math.ceil((width - OVERLAP_PT) / (tile_w - OVERLAP_PT)))
    rows = max(1, math.ceil((height - OVERLAP_PT) / (tile_h - OVERLAP_PT)))
    step_x = (width - tile_w) / (cols - 1) if cols > 1 else 0.0
    step_y = (height - tile_h) / (rows - 1) if rows > 1 else 0.0
    out = [
        fitz.Rect(c * step_x, r * step_y, min(width, c * step_x + tile_w), min(height, r * step_y + tile_h))
        for r in range(rows)
        for c in range(cols)
    ]
    return out[:MAX_TILES]


def render_tile(page: fitz.Page, rect: fitz.Rect) -> tuple[bytes, float]:
    """PNG of one display-space rectangle, and the scale it was rendered at.

    `get_pixmap` renders the page as displayed and takes `clip` in that same
    frame, so a display rectangle goes in unchanged - pinned by a test on a
    270-rotated sheet, which is most of a real bid set.
    """
    landscape = rect.width >= rect.height
    max_w, max_h = (MAX_W, MAX_H) if landscape else (MAX_H, MAX_W)
    scale = min(max_w / rect.width, max_h / rect.height, TILE_SCALE * 2)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    return pix.tobytes("png"), scale


def _blocks_from(response: dict[str, Any]) -> list[dict[str, Any]]:
    """The markdown_bbox tool call's argument list, flattened."""
    choices = response.get("choices") or []
    if not choices:
        raise NimError("no choices in response")
    message = choices[0].get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        raise NimError(f"no tool call in response: {str(message.get('content'))[:200]}")
    raw = calls[0].get("function", {}).get("arguments")
    data = json.loads(raw) if isinstance(raw, str) else raw
    # One list per image; a single image answers with [[...]] or [...].
    if isinstance(data, list) and data and isinstance(data[0], list):
        data = [block for inner in data for block in inner]
    if not isinstance(data, list):
        raise NimError("markdown_bbox arguments were not a list")
    return [block for block in data if isinstance(block, dict)]


def _to_page(block: dict[str, Any], rect: fitz.Rect) -> dict[str, Any] | None:
    box = block.get("bbox") or {}
    try:
        x0, y0, x1, y1 = (float(box[k]) for k in ("xmin", "ymin", "xmax", "ymax"))
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1.0001 and 0 <= y0 < y1 <= 1.0001):
        return None
    text = str(block.get("text") or "").strip()
    return {
        "type": str(block.get("type") or "Text").lower(),
        "text": text,
        "bbox": [
            round(rect.x0 + x0 * rect.width, 2), round(rect.y0 + y0 * rect.height, 2),
            round(rect.x0 + x1 * rect.width, 2), round(rect.y0 + y1 * rect.height, 2),
        ],
    }


def _dedupe(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A block read in two tiles' overlap is one block: same text, boxes mostly shared."""
    kept: list[dict[str, Any]] = []
    for block in blocks:
        rect = fitz.Rect(block["bbox"])
        duplicate = False
        for other in kept:
            if other["text"] != block["text"]:
                continue
            o = fitz.Rect(other["bbox"])
            inter = (rect & o).get_area()
            if inter and inter >= 0.5 * min(rect.get_area(), o.get_area()):
                duplicate = True
                break
        if not duplicate:
            kept.append(block)
    return kept


async def _call(
    client: httpx.AsyncClient, *, api_key: str, model: str, png: bytes, gate: Pacer, attempts: int = 4
) -> list[dict[str, Any]]:
    body = {
        "model": model,
        "tools": [{"type": "function", "function": {"name": "markdown_bbox"}}],
        "messages": [{"role": "user", "content": [{
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")},
        }]}],
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    for attempt in range(attempts):
        await gate.wait()
        try:
            response = await client.post(API_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            if attempt + 1 == attempts:
                raise NimError(f"NIM unreachable: {exc}") from exc
            await asyncio.sleep(2 ** attempt)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            # The pacer counts our calls; NVIDIA counts its own. Wait as told.
            retry = float(response.headers.get("retry-after") or 2 ** (attempt + 2))
            if attempt + 1 == attempts:
                raise NimError(f"NIM {response.status_code} after {attempts} attempts")
            await asyncio.sleep(min(retry, 60.0))
            continue
        if response.status_code >= 400:
            raise NimError(f"NIM {response.status_code}: {response.text[:200]}")
        return _blocks_from(response.json())
    raise NimError("NIM gave no answer")


async def parse_page(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    pdf_path: str | Path,
    page_number: int,
    model: str = DEFAULT_MODEL,
    rpm: int = DEFAULT_RPM,
) -> dict[str, Any]:
    """One page as `{"page", "width", "height", "items"}`, boxes in display-space points."""
    document = fitz.open(str(pdf_path))
    try:
        page = document[page_number - 1]
        width, height = page.rect.width, page.rect.height
        rendered = [(rect, render_tile(page, rect)[0]) for rect in tiles(width, height)]
    finally:
        document.close()

    gate = pacer(rpm)
    answers = await asyncio.gather(*(
        _call(client, api_key=api_key, model=model, png=png, gate=gate) for _rect, png in rendered
    ))
    items = [
        mapped
        for (rect, _png), blocks in zip(rendered, answers)
        for block in blocks
        if (mapped := _to_page(block, rect)) is not None
    ]
    # Tile order (row by row) and the model's own order within a tile: reading
    # order. Sorting by y across tiles would interleave a sheet's columns.
    return {"page": page_number, "width": width, "height": height, "items": _dedupe(items)}
