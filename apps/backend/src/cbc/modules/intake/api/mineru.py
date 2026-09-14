"""Normalise MinerU middle.json into per-page documentPages rows.

Covers pipeline, hybrid-engine and vlm-engine shapes: nested list/code blocks,
spans, discarded_blocks (sheet numbers / titles), and table HTML on spans.

Bboxes are stored in the rotated display frame used by `page_size` and the
viewer. When MinerU's page_size is PyMuPDF's page.rect transposed, each bbox is
mapped through `page.rotation_matrix`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from cbc.shared.pdfrows import rows_from_words

# Same threshold as extraction bbox verification: half the claim on real text.
BBOX_COVERAGE = 0.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bbox(raw: Any) -> list[float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        return None
    try:
        box = [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])]
    except (TypeError, ValueError):
        return None
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return [round(v, 2) for v in box]


def _join_spans(spans: list[Any]) -> str:
    parts: list[str] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        text = span.get("content") or span.get("text") or ""
        if text:
            parts.append(str(text))
    return "".join(parts)


def _block_text(block: dict[str, Any]) -> str:
    if block.get("content"):
        return str(block["content"]).strip()
    lines = block.get("lines")
    if isinstance(lines, list):
        chunks: list[str] = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            if line.get("content"):
                chunks.append(str(line["content"]))
            elif isinstance(line.get("spans"), list):
                chunks.append(_join_spans(line["spans"]))
        return "\n".join(c for c in chunks if c).strip()
    spans = block.get("spans")
    if isinstance(spans, list):
        return _join_spans(spans).strip()
    return ""


def _line_entries(block: dict[str, Any]) -> list[dict[str, Any]]:
    lines = block.get("lines")
    if not isinstance(lines, list):
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        box = _bbox(line.get("bbox"))
        text = ""
        if line.get("content"):
            text = str(line["content"])
        elif isinstance(line.get("spans"), list):
            text = _join_spans(line["spans"])
        if box is None and not text:
            continue
        entry: dict[str, Any] = {"text": text}
        if box is not None:
            entry["bbox"] = box
        out.append(entry)
    return out


def _table_html(block: dict[str, Any]) -> str | None:
    """Table HTML lives on a span in MinerU middle.json."""
    for key in ("html", "table_html", "table_body"):
        if block.get(key):
            return str(block[key])
    spans = block.get("spans")
    if isinstance(spans, list):
        for span in spans:
            if isinstance(span, dict) and span.get("html"):
                return str(span["html"])
            if isinstance(span, dict) and span.get("type") == "table" and span.get("content"):
                return str(span["content"])
    lines = block.get("lines")
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            for span in line.get("spans") or []:
                if isinstance(span, dict) and span.get("html"):
                    return str(span["html"])
    return None


def _block_type(block: dict[str, Any], *, discarded: bool = False) -> str:
    if discarded:
        return "discarded"
    raw = block.get("type") or block.get("block_type") or "text"
    return str(raw).lower().replace(" ", "_")


def walk_blocks(
    blocks: list[Any] | None, *, discarded: bool = False
) -> list[dict[str, Any]]:
    """Flatten nested MinerU blocks into [{type, text, bbox, lines, html?}]."""
    if not isinstance(blocks, list):
        return []
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        nested = block.get("blocks")
        if isinstance(nested, list) and nested:
            out.extend(walk_blocks(nested, discarded=discarded))
            continue
        # list / code sub-types nest items under `blocks` or `lines` already handled
        for sub_key in ("list_items", "code_body"):
            sub = block.get(sub_key)
            if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                out.extend(walk_blocks(sub, discarded=discarded))
        text = _block_text(block)
        box = _bbox(block.get("bbox"))
        entry: dict[str, Any] = {
            "type": _block_type(block, discarded=discarded),
            "text": text,
        }
        if box is not None:
            entry["bbox"] = box
        lines = _line_entries(block)
        if lines:
            entry["lines"] = lines
        html = _table_html(block) if entry["type"] in {"table", "table_body"} or block.get("type") == "table" else None
        if html:
            entry["html"] = html
            entry["type"] = "table"
        angle = block.get("angle")
        if angle is not None:
            entry["angle"] = angle
        if box is not None or text or html:
            out.append(entry)
    return out


def _pages_from_middle(middle: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(middle, list):
        return [p for p in middle if isinstance(p, dict)]
    for key in ("pdf_info", "pages", "page_info"):
        pages = middle.get(key)
        if isinstance(pages, list):
            return [p for p in pages if isinstance(p, dict)]
        if isinstance(pages, dict):
            return [p for p in pages.values() if isinstance(p, dict)]
    return []


def load_middle(raw: dict[str, Any] | list[Any] | str | Path) -> dict[str, Any] | list[Any]:
    if isinstance(raw, (str, Path)):
        text = Path(raw).read_text(encoding="utf-8") if Path(str(raw)).is_file() else str(raw)
        return json.loads(text)
    return raw


def _needs_rotation(mineru_size: tuple[float, float], page: fitz.Page) -> bool:
    """True when MinerU's page_size is the unrotated frame vs page.rect."""
    mw, mh = mineru_size
    dw, dh = page.rect.width, page.rect.height
    if not page.rotation:
        return False
    # Transposed relative to display rect (typical 90/270).
    if abs(mw - dw) < 1 and abs(mh - dh) < 1:
        return False
    if abs(mw - dh) < 2 and abs(mh - dw) < 2:
        return True
    # Also rotate when mediabox matches MinerU and differs from display.
    mb = page.mediabox
    if abs(mw - mb.width) < 2 and abs(mh - mb.height) < 2:
        if abs(mw - dw) > 1 or abs(mh - dh) > 1:
            return True
    return False


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
        if "bbox" in mapped:
            mapped["bbox"] = _map_bbox(mapped["bbox"], matrix)
        if "lines" in mapped:
            lines = []
            for line in mapped["lines"]:
                item = dict(line)
                if "bbox" in item:
                    item["bbox"] = _map_bbox(item["bbox"], matrix)
                lines.append(item)
            mapped["lines"] = lines
        out.append(mapped)
    return out


def verify_page(page: fitz.Page, blocks: list[dict[str, Any]]) -> float | None:
    """Share of text blocks ≥50% covered by pdfrows boxes. None if no text layer."""
    text_blocks = [
        b
        for b in blocks
        if b.get("bbox")
        and (b.get("text") or "").strip()
        and b.get("type") not in {"discarded", "image", "figure"}
    ]
    if not text_blocks:
        return None
    rows = rows_from_words(page)
    if not rows and not page.get_text("text").strip():
        return None
    boxes = [fitz.Rect(r["bbox"]) for r in rows]
    for row in rows:
        boxes.extend(fitz.Rect(c) for c in row.get("cell_boxes") or [])
    if not boxes:
        # Has a text layer but row clustering found nothing — still verifiable as 0.
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


def normalise_window(
    middle: dict[str, Any] | list[Any] | str | Path,
    *,
    pdf_path: str | Path,
    start_page: int,
    project_id: Any,
    document_id: Any,
    content_sha: str,
    parser: dict[str, Any],
) -> list[dict[str, Any]]:
    """Turn one MinerU window result into documentPages documents (1-based pages)."""
    data = load_middle(middle)
    if isinstance(data, dict) and "middle_json" in data:
        inner = data["middle_json"]
        if isinstance(inner, str):
            data = json.loads(inner)
        else:
            data = inner
    pages = _pages_from_middle(data if isinstance(data, (dict, list)) else {})
    doc = fitz.open(pdf_path)
    try:
        results: list[dict[str, Any]] = []
        for offset, page_info in enumerate(pages):
            page_number = start_page + offset
            index = page_number - 1
            if not 0 <= index < doc.page_count:
                continue
            page = doc[index]
            size_raw = page_info.get("page_size") or page_info.get("page_size_pts")
            if isinstance(size_raw, (list, tuple)) and len(size_raw) >= 2:
                mineru_size = (float(size_raw[0]), float(size_raw[1]))
            else:
                mineru_size = (page.mediabox.width, page.mediabox.height)

            blocks = walk_blocks(page_info.get("para_blocks") or page_info.get("preproc_blocks"))
            blocks.extend(
                walk_blocks(page_info.get("discarded_blocks"), discarded=True)
            )
            # Some shapes put everything under `blocks`.
            if not blocks and isinstance(page_info.get("blocks"), list):
                blocks = walk_blocks(page_info["blocks"])

            matrix = page.rotation_matrix if _needs_rotation(mineru_size, page) else None
            blocks = _transform_blocks(blocks, matrix)
            numbered = []
            for n, block in enumerate(blocks, start=1):
                numbered.append({"n": n, **block})

            verified = verify_page(page, numbered)
            results.append(
                {
                    "projectId": project_id,
                    "documentId": document_id,
                    "contentSha": content_sha,
                    "page": page_number,
                    "pageSize": {
                        "width": round(page.rect.width, 2),
                        "height": round(page.rect.height, 2),
                    },
                    "blocks": numbered,
                    "verified": verified,
                    "parser": dict(parser),
                    "parsedAt": _now(),
                }
            )
        return results
    finally:
        doc.close()
