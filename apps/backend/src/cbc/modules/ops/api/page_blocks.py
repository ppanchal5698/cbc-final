"""Turn one parsed window into per-page `documentPages` rows.

The parser hands over a neutral window payload (see `ops.api.llamaparse`):

    {"page": 19, "width": 2448.0, "height": 1584.0,
     "items": [{"type", "text", "bbox": [x0,y0,x1,y1],
                "lines": [{"text","bbox"}]?, "cells": [[x0,y0,x1,y1]]?}]}

and this module decides the two things that make a box trustworthy: which frame
it belongs in, and whether it lands on text that is genuinely there.

**Frame.** `pageSize` is always PyMuPDF's `page.rect` - the rotated display frame
the viewer scales against - and never the parser's own reported size. That is
what lets the parser change without every stored bbox moving. 72 of the 87 pages
in the first real bid set are rotated 270, so this is the common path, not an
edge case.

**Orientation.** MinerU reported against the unrotated mediabox and needed
`page.rotation_matrix`. LlamaParse reports display space already - measured on a
270-rotated sheet it returned 2448x1584 with every box inside that frame - so
mapping its boxes would push them off the page. `_oriented` settles it by size
where size is decisive and by coverage where it is not, and `reports_unrotated`
records the parser's convention for the case nothing can be scored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from cbc.shared.pdfrows import rows_from_words

# Same threshold as extraction bbox verification: half the claim on real text.
BBOX_COVERAGE = 0.5

# Types that legitimately carry no text to anchor, so they keep their place in
# the page without being scored or dropped.
_BBOX_EXEMPT_TYPES = frozenset({"image", "figure"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_box(box: Any) -> bool:
    return (
        isinstance(box, (list, tuple))
        and len(box) == 4
        and all(isinstance(v, (int, float)) for v in box)
        and box[2] > box[0]
        and box[3] > box[1]
    )


def _needs_rotation(reported: tuple[float, float], page: fitz.Page) -> bool:
    """True when the parser's page size is the unrotated frame vs page.rect."""
    mw, mh = reported
    dw, dh = page.rect.width, page.rect.height
    if not page.rotation:
        return False
    if abs(mw - dw) < 1 and abs(mh - dh) < 1:
        return False
    if abs(mw - dh) < 2 and abs(mh - dw) < 2:
        return True
    mb = page.mediabox
    if abs(mw - mb.width) < 2 and abs(mh - mb.height) < 2:
        if abs(mw - dw) > 1 or abs(mh - dh) > 1:
            return True
    return False


def _rotation_is_ambiguous(page: fitz.Page) -> bool:
    """True when page size cannot tell the two frames apart.

    Size decides at 90/270, where the frames are transposed. It cannot decide at
    180, where the rotated and unrotated frames are the *same size* while the
    transform is real: (x,y) -> (W-x, H-y). The size test matches, no matrix is
    applied, and every box lands point-mirrored under a page_size that looks
    correct - so the frame check passes and the highlight sits in the opposite
    corner. A square page has the same blind spot at 90/270.
    """
    if not page.rotation:
        return False
    if page.rotation == 180:
        return True
    return abs(page.rect.width - page.rect.height) <= 2


def _map_bbox(box: list[float], matrix: fitz.Matrix) -> list[float]:
    rect = (fitz.Rect(box) * matrix).normalize()
    return [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]


def _transform_blocks(
    blocks: list[dict[str, Any]], matrix: fitz.Matrix | None
) -> list[dict[str, Any]]:
    if matrix is None:
        return blocks
    out: list[dict[str, Any]] = []
    for block in blocks:
        mapped = dict(block)
        if _valid_box(mapped.get("bbox")):
            mapped["bbox"] = _map_bbox(mapped["bbox"], matrix)
        if mapped.get("lines"):
            lines = []
            for line in mapped["lines"]:
                item = dict(line)
                if _valid_box(item.get("bbox")):
                    item["bbox"] = _map_bbox(item["bbox"], matrix)
                lines.append(item)
            mapped["lines"] = lines
        if mapped.get("cells"):
            mapped["cells"] = [
                _map_bbox(c, matrix) if _valid_box(c) else c for c in mapped["cells"]
            ]
        out.append(mapped)
    return out


def verify_page(
    page: fitz.Page,
    blocks: list[dict[str, Any]],
    *,
    rows: list[dict[str, Any]] | None = None,
) -> float | None:
    """Share of text blocks >=50% covered by pdfrows boxes. None if no text layer.

    `rows` lets a caller that already clustered the page pass the result in;
    `_oriented` scores the same page twice and clustering it twice to answer one
    question turns a per-page check into a per-run cost.
    """
    text_blocks = [
        b
        for b in blocks
        if b.get("bbox")
        and (b.get("text") or "").strip()
        and b.get("type") not in {"discarded", "image", "figure"}
    ]
    if not text_blocks:
        return None
    if rows is None:
        rows = rows_from_words(page)
    if not rows and not page.get_text("text").strip():
        return None
    boxes = [fitz.Rect(r["bbox"]) for r in rows]
    for row in rows:
        boxes.extend(fitz.Rect(c) for c in row.get("cell_boxes") or [])
    if not boxes:
        # Has a text layer but row clustering found nothing - verifiable as 0.
        if page.get_text("text").strip():
            return 0.0
        return None
    hits = 0
    for block in text_blocks:
        claim = fitz.Rect(block["bbox"])
        area = claim.get_area()
        if not area:
            continue
        covered = max((claim & other).get_area() / area for other in boxes)
        if covered >= BBOX_COVERAGE:
            hits += 1
    return round(hits / len(text_blocks), 4)


def _oriented(
    blocks: list[dict[str, Any]],
    page: fitz.Page,
    reported_size: tuple[float, float],
    *,
    reports_unrotated: bool = False,
) -> list[dict[str, Any]]:
    """Blocks in display space. Size settles 90/270; coverage settles the rest.

    Where size is decisive we trust it - exact and free. Where it cannot be (180,
    square pages) we ask `verify_page`, already the oracle for "do these boxes
    land on real text": score both orientations against the page's own words and
    keep the winner.

    `reports_unrotated` is the parser's own convention and only decides the case
    where nothing can be scored (no text layer, no boxed text). Guessing one
    convention for both parsers is how a highlight ends up in the wrong corner on
    exactly the pages nobody can check.
    """
    if not page.rotation:
        return blocks
    if not _rotation_is_ambiguous(page):
        matrix = page.rotation_matrix if _needs_rotation(reported_size, page) else None
        return _transform_blocks(blocks, matrix)

    mapped = _transform_blocks(blocks, page.rotation_matrix)
    rows = rows_from_words(page)
    plain_score = verify_page(page, blocks, rows=rows)
    mapped_score = verify_page(page, mapped, rows=rows)
    if plain_score is None or mapped_score is None:
        return mapped if reports_unrotated else blocks
    return mapped if mapped_score >= plain_score else blocks


def _require_bbox(
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Drop text blocks with no usable bbox. Returns (kept, dropped_count).

    A block used to survive on text alone, so text with no rectangle reached
    Mongo, reached the agent through bid-docs (where a null bbox is
    indistinguishable from a real one), and could become a quoted line with
    nothing on a sheet to point at. NFR-3 makes the box mandatory, and the
    opening-level validator only catches it much later - by which point the
    estimator is already looking at the number.

    Dropping beats keeping it unboxed: a parser only boxes text literally on the
    page, so text without one was inferred. Losing it shows up as a lower
    `verified`, which routes the page to a visual read - the outcome we want -
    rather than a confident untraceable value.
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for block in blocks:
        text = (block.get("text") or "").strip()
        exempt = block.get("type") in _BBOX_EXEMPT_TYPES
        if text and not exempt and not _valid_box(block.get("bbox")):
            dropped += 1
            continue
        kept.append(block)
    return kept, dropped


def normalise_window(
    pages: list[dict[str, Any]],
    *,
    pdf_path: str | Path,
    project_id: Any,
    document_id: Any,
    content_sha: str,
    parser: dict[str, Any],
    reports_unrotated: bool = False,
) -> list[dict[str, Any]]:
    """Window payload -> documentPages rows, 1-based pages in display space.

    The window payload already carries absolute 1-based page numbers, so there is
    no `start_page` to add. The previous normaliser derived the page by
    enumeration order, and a parser that dropped or reordered one page inside a
    window filed every later block under the wrong sheet - silently, because
    `verified` was then computed against whichever page the code believed it was.
    """
    document = fitz.open(pdf_path)
    try:
        results: list[dict[str, Any]] = []
        for entry in pages:
            number = entry.get("page")
            if not isinstance(number, int):
                continue
            index = number - 1
            if not 0 <= index < document.page_count:
                continue
            page = document[index]

            width = float(entry.get("width") or 0.0)
            height = float(entry.get("height") or 0.0)
            reported = (width, height) if width and height else (
                page.mediabox.width,
                page.mediabox.height,
            )

            blocks = [dict(b) for b in entry.get("items") or []]
            blocks = _oriented(
                blocks, page, reported, reports_unrotated=reports_unrotated
            )
            blocks, dropped_no_bbox = _require_bbox(blocks)
            numbered = [{"n": n, **block} for n, block in enumerate(blocks, start=1)]

            results.append(
                {
                    "projectId": project_id,
                    "documentId": document_id,
                    "contentSha": content_sha,
                    "page": number,
                    "pageSize": {
                        "width": round(page.rect.width, 2),
                        "height": round(page.rect.height, 2),
                    },
                    "blocks": numbered,
                    "verified": verify_page(page, numbered),
                    "droppedNoBbox": dropped_no_bbox,
                    "parser": dict(parser),
                    "parsedAt": _now(),
                }
            )
        return results
    finally:
        document.close()
