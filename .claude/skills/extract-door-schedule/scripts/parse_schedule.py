#!/usr/bin/env python3
"""Extract door / frame / hardware schedules from an architectural PDF.

Architectural sheets are CAD exports with no reliable table ruling, so rows are
recovered by clustering positioned words on the y-axis. Verified against the
Dutch Bros fixture (1_Architectural.pdf, sheet A2.2, page 14).

Usage:
    python parse_schedule.py <pdf> --find            # locate schedule pages
    python parse_schedule.py <pdf> --page 14         # dump clustered rows
    python parse_schedule.py <pdf> --page 14 --json  # machine-readable rows
    python parse_schedule.py --demo                  # runnable self-check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    sys.exit("PyMuPDF is required: python -m pip install PyMuPDF")

ROW_TOLERANCE = 6.0
COLUMN_GAP = 12.0

SCHEDULE_MARKERS = [
    "DOOR SCHEDULE",
    "DOOR TYPE SCHEDULE",
    "DOOR FRAME TYPE SCHEDULE",
    "FRAME SCHEDULE",
    "HARDWARE GROUPS",
    "HARDWARE SCHEDULE",
    "WINDOW SCHEDULE",
    "FINISH SCHEDULE",
]

SIZE_4DIGIT = re.compile(r"\b([2-9])([0-9])([4-9])([0-9])\b")
SIZE_EXPLICIT = re.compile(r"(\d+)'\s*-?\s*(\d+)\"")
HANDING = re.compile(r"\b(LHR|RHR|LH|RH)\b")
FIRE_RATING = re.compile(r"\b(20|45|60|90|180)\s*(?:MIN|MINUTE)?\b", re.IGNORECASE)
HW_GROUP = re.compile(r"\b(?:GROUP|HW|HDW|HG)[\s-]*(\d+)\b", re.IGNORECASE)
FINISH = re.compile(r"\b(US\d{1,2}[A-Z]?|6\d{2})\b")
DOOR_MARK = re.compile(r"^\s*(\d{2,3}[A-Z]?)\b")


def _open(pdf_path: str) -> fitz.Document:
    path = Path(pdf_path)
    if not path.exists():
        sys.exit(f"PDF not found: {pdf_path}")
    return fitz.open(path)


def find_schedule_pages(pdf_path: str) -> list[dict[str, Any]]:
    """Return every page carrying a schedule marker, with which markers it holds."""
    doc = _open(pdf_path)
    try:
        found = []
        for index in range(doc.page_count):
            upper = doc[index].get_text().upper()
            markers = [m for m in SCHEDULE_MARKERS if m in upper]
            if markers:
                found.append({"source_page": index + 1, "markers": markers})
        return found
    finally:
        doc.close()


def _bbox(words: list[tuple]) -> list[float]:
    """Union bounding box of a group of words, as [x0, y0, x1, y1] in PDF points."""
    return [
        round(min(w[0] for w in words), 2),
        round(min(w[1] for w in words), 2),
        round(max(w[2] for w in words), 2),
        round(max(w[3] for w in words), 2),
    ]


def page_size(pdf_path: str, page_number: int) -> dict[str, float]:
    """Page dimensions in PDF points - the frame a bbox is measured against."""
    doc = _open(pdf_path)
    try:
        rect = doc[page_number - 1].rect
        return {"width": round(rect.width, 2), "height": round(rect.height, 2)}
    finally:
        doc.close()


def cluster_rows(
    pdf_path: str, page_number: int, region: list[float] | None = None
) -> list[dict[str, Any]]:
    """Cluster a page's positioned words into rows of cells.

    Every row and every cell keeps its bounding box. The viewer draws the
    highlight from these, so the estimator checks the extraction against the
    real drawing rather than against a re-rendering of the extraction.
    """
    doc = _open(pdf_path)
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            sys.exit(f"page {page_number} out of range (1-{doc.page_count})")
        page = doc[index]
        words = page.get_text("words")
        size = {"width": round(page.rect.width, 2), "height": round(page.rect.height, 2)}
    finally:
        doc.close()

    if region:
        x0, y0, x1, y1 = region
        words = [w for w in words if x0 <= w[0] <= x1 and y0 <= w[1] <= y1]
    if not words:
        return []

    buckets: dict[int, list[tuple]] = defaultdict(list)
    for word in words:
        buckets[int(word[1] // ROW_TOLERANCE)].append(word)

    rows: list[dict[str, Any]] = []
    for key in sorted(buckets):
        line = sorted(buckets[key], key=lambda w: w[0])
        cells: list[dict[str, Any]] = []
        current = [line[0]]
        for word in line[1:]:
            if word[0] - current[-1][2] > COLUMN_GAP:
                cells.append({"text": " ".join(w[4] for w in current), "bbox": _bbox(current)})
                current = [word]
            else:
                current.append(word)
        cells.append({"text": " ".join(w[4] for w in current), "bbox": _bbox(current)})
        rows.append(
            {
                "source_page": page_number,
                "page_size": size,
                "bbox": _bbox(line),
                "y": round(line[0][1], 1),
                "x_start": round(line[0][0], 1),
                "cells": [c["text"] for c in cells],
                "cell_boxes": [c["bbox"] for c in cells],
                "text": " | ".join(c["text"] for c in cells),
            }
        )
    return rows


def parse_size(text: str) -> dict[str, Any]:
    """Resolve either 4-digit shorthand or explicit feet-inches into width/height."""
    explicit = SIZE_EXPLICIT.findall(text)
    if len(explicit) >= 2:
        (wf, wi), (hf, hi) = explicit[0], explicit[1]
        return {
            "size": f"{wf}{wi}{hf}{hi}" if len(wi) == 1 and len(hi) == 1 else None,
            "width": f"{wf}'-{wi}\"",
            "height": f"{hf}'-{hi}\"",
            "notation": "explicit",
        }
    shorthand = SIZE_4DIGIT.search(text)
    if shorthand:
        wf, wi, hf, hi = shorthand.groups()
        return {
            "size": f"{wf}{wi}{hf}{hi}",
            "width": f"{wf}'-{wi}\"",
            "height": f"{hf}'-{hi}\"",
            "notation": "4-digit",
        }
    return {"size": None, "width": None, "height": None, "notation": None}


def highlight_bbox(row: dict[str, Any]) -> list[float] | None:
    """Tighten the row bbox down to the cells that actually carry the opening.

    A CAD sheet puts unrelated notes on the same horizontal band as a schedule
    row, so the raw row bbox can span the whole page. The useful highlight runs
    from the cell holding the size to the cell holding the hardware group.
    """
    cells, boxes = row.get("cells") or [], row.get("cell_boxes") or []
    if not boxes or len(cells) != len(boxes):
        return row.get("bbox")

    anchors = [
        i
        for i, cell in enumerate(cells)
        if SIZE_EXPLICIT.search(cell) or SIZE_4DIGIT.search(cell) or HW_GROUP.search(cell)
    ]
    if not anchors:
        return row.get("bbox")

    # A schedule row ends at its hardware group; anything further right on the
    # same band is unrelated sheet text - a drawing scale note, most often.
    groups = [i for i, cell in enumerate(cells) if HW_GROUP.search(cell)]
    if groups:
        anchors = [i for i in anchors if i <= groups[0]] or [groups[0]]

    span = boxes[min(anchors) : max(anchors) + 1]
    return [
        round(min(b[0] for b in span), 2),
        round(min(b[1] for b in span), 2),
        round(max(b[2] for b in span), 2),
        round(max(b[3] for b in span), 2),
    ]


def _door_number_from_row(row: dict[str, Any]) -> str | None:
    cells = row.get("cells") or []
    for cell in cells[:4]:
        cell_text = str(cell).strip()
        if re.fullmatch(r"\d{2,3}[A-Z]?", cell_text):
            return cell_text
        lead = DOOR_MARK.match(cell_text)
        if lead:
            return lead.group(1)
    lead = DOOR_MARK.match(row.get("text", "").strip())
    return lead.group(1) if lead else None


def _row_is_opening(row: dict[str, Any]) -> bool:
    text = row.get("text", "")
    has_explicit = bool(SIZE_EXPLICIT.search(text))
    has_4digit = bool(SIZE_4DIGIT.search(text))
    has_group = bool(HW_GROUP.search(text))
    if has_explicit and has_group:
        return True
    # 4-digit shorthand without inline hardware group, but with a real door mark.
    return bool(has_4digit and not has_explicit and _door_number_from_row(row))


def parse_opening(row: dict[str, Any]) -> dict[str, Any]:
    """Best-effort field extraction from one clustered row.

    Missing attributes stay null and are flagged. Nothing is inferred from a
    neighbouring row (.claude/rules/accuracy-trust.md).
    """
    text = row["text"]
    size = parse_size(text)
    handing = HANDING.search(text)
    rating = FIRE_RATING.search(text)
    group = HW_GROUP.search(text)
    finish = FINISH.search(text)

    opening = {
        "door_number": _door_number_from_row(row),
        "size": size["size"],
        "width": size["width"],
        "height": size["height"],
        "size_notation": size["notation"],
        "handing": handing.group(1) if handing else None,
        "fire_rating": rating.group(1) if rating else None,
        "finish": finish.group(1) if finish else None,
        "hardware_set": f"GROUP {group.group(1)}" if group else None,
        "source_page": row["source_page"],
        # Provenance the viewer needs to put a highlight on the real page (NFR-3).
        "page_size": row.get("page_size"),
        "bbox": highlight_bbox(row),
        "row_bbox": row.get("bbox"),
        "cell_boxes": row.get("cell_boxes"),
        "raw_row": text,
    }
    opening["flags"] = [
        f"{field}_missing"
        for field in ("fire_rating", "handing", "finish", "hardware_set")
        if opening[field] is None
    ]
    opening["confidence"] = round(max(0.3, 1.0 - 0.15 * len(opening["flags"])), 2)
    return opening


def schedule_rows(pdf_path: str, page_number: int) -> list[dict[str, Any]]:
    """Rows that plausibly describe an opening: size notation with optional hardware group."""
    out = []
    for row in cluster_rows(pdf_path, page_number):
        if _row_is_opening(row):
            out.append(parse_opening(row))
    return out


def openings_envelope(pdf_path: str, page_number: int, source_file: str | None = None) -> dict[str, Any]:
    """Full door_schedule.json payload with provenance on every opening."""
    return {
        "source_file": source_file,
        "source_page": page_number,
        "openings": schedule_rows(pdf_path, page_number),
    }


def _demo() -> None:
    """Runnable check for the size parser - the one piece with real branching."""
    assert parse_size("3070")["width"] == "3'-0\""
    assert parse_size("3070")["height"] == "7'-0\""
    assert parse_size("3670")["width"] == "3'-6\""
    explicit = parse_size("01 3' - 6\" | 7' - 0\" | A")
    assert explicit["width"] == "3'-6\"" and explicit["height"] == "7'-0\""
    assert explicit["notation"] == "explicit"
    assert parse_size("no size here")["size"] is None

    row = {
        "source_page": 14,
        "text": "01 3' - 6\" | 7' - 0\" | A | 1 | TEMP. HM HMD | GROUP 1",
        "page_size": {"width": 2592.0, "height": 1728.0},
        "bbox": [640.2, 609.8, 998.4, 619.1],
        "cell_boxes": [[640.2, 609.8, 690.0, 619.1]],
    }
    opening = parse_opening(row)
    assert opening["door_number"] == "01"
    assert opening["hardware_set"] == "GROUP 1"
    assert opening["fire_rating"] is None
    assert "fire_rating_missing" in opening["flags"]
    assert opening["source_page"] == 14
    assert len(opening["bbox"]) == 4, "the viewer cannot draw a highlight without a bbox"
    assert opening["page_size"]["width"] == 2592.0
    print("parse_schedule demo OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", help="Path to the architectural PDF")
    parser.add_argument("--find", action="store_true", help="Locate schedule pages")
    parser.add_argument("--page", type=int, help="Page to cluster (1-indexed)")
    parser.add_argument("--openings", action="store_true", help="Parse opening rows only")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--demo", action="store_true", help="Run the self-check")
    args = parser.parse_args()

    if args.demo:
        _demo()
        return 0
    if not args.pdf:
        parser.error("a PDF path is required unless --demo is given")

    if args.find or not args.page:
        pages = find_schedule_pages(args.pdf)
        print(json.dumps(pages, indent=2) if args.json else "")
        if not args.json:
            for page in pages:
                print(f"page {page['source_page']:>3}: {', '.join(page['markers'])}")
        return 0

    payload = schedule_rows(args.pdf, args.page) if args.openings else cluster_rows(args.pdf, args.page)
    if args.json:
        if args.openings:
            print(json.dumps(openings_envelope(args.pdf, args.page, source_file=args.pdf), indent=2))
        else:
            print(json.dumps(payload, indent=2))
    else:
        for item in payload:
            print(item.get("raw_row") or item.get("text"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
