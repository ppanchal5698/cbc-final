#!/usr/bin/env python3
"""Extract door / frame / hardware schedules from an architectural PDF.

Architectural sheets are CAD exports with no reliable table ruling. Rows are
recovered by clustering positioned words on the y-axis in *display* space
(after applying page.rotation_matrix). Without that transform, 270°-rotated
sheets cluster columns as rows and return zero openings.

Supports layout classes A–D (GROUP, hardware-matrix, inch-layout, remodel empty)
across diverse bid sets — do not hard-code a single project sheet ID or brand.

Usage:
    python parse_schedule.py <pdf> --find
    python parse_schedule.py <pdf> --page 19 --openings --json
    python parse_schedule.py --demo
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
    "OPENING SCHEDULE",
    "DOOR AND FRAME SCHEDULE",
    "DOOR & FRAME SCHEDULE",
    "DOOR HARDWARE SCHEDULE",
    "HARDWARE GROUPS",
    "HARDWARE SCHEDULE",
    "HW SCHEDULE",
    "WINDOW SCHEDULE",
    "FINISH SCHEDULE",
]

# FR-2 / Matrix 7.1 — 4-digit shorthand, explicit feet-inches, or inch-only columns.
SIZE_4DIGIT = re.compile(r"\b([2-9])([0-9])([4-9])([0-9])\b")
SIZE_EXPLICIT = re.compile(r"(\d+)\s*'\s*-?\s*(\d+)\s*\"")
# Retail / quick-serve schedules often print WIDTH/HGT as bare inches: 36" × 84".
SIZE_INCHES = re.compile(r"\b(\d{2,3})\s*\"")
HANDING = re.compile(
    r"\b(LHR|RHR|LH|RH|L\.H\.R\.|R\.H\.R\.|L\.H\.|R\.H\.|LEFT\s*HAND(?:\s*REVERSE)?|"
    r"RIGHT\s*HAND(?:\s*REVERSE)?)\b",
    re.IGNORECASE,
)
# Matrix 7.3 interim — common minute labels + NR. Never invent when absent.
FIRE_RATING = re.compile(
    r"\b(?:(20|45|60|90|180)\s*(?:MIN(?:UTE)?S?)?|"
    r"(?:1|ONE)\s*(?:HR|HOUR)|"
    r"(?:N/?R|NON[-\s]?RATED|UNRATED))\b",
    re.IGNORECASE,
)
# The same ratings, but only where the text names a unit. Used when no column
# was mapped, so a note number can never be mistaken for a rating.
FIRE_RATING_QUALIFIED = re.compile(
    r"\b(?:(20|45|60|90|180)\s*MIN(?:UTE)?S?|"
    r"(?:1|ONE)\s*(?:HR|HOUR)|"
    r"(?:N/?R|NON[-\s]?RATED|UNRATED))\b",
    re.IGNORECASE,
)

HW_GROUP = re.compile(r"\b(?:GROUP|HW|HDW|HG)[\s-]*(\d+)\b", re.IGNORECASE)
# Column that is just "5" under a HARDWARE GROUP header.
HW_GROUP_BARE = re.compile(r"^\d{1,3}$")
FINISH = re.compile(r"\b(US\d{1,2}[A-Z]?|6\d{2})\b")
# Marks: numeric (1, 01, 101A) or letter-first / hyphenated (A-1, D.01, L101).
# Never treat a dimension like 12'-1" as a mark — require a bare cell.
DOOR_MARK_CELL = re.compile(
    r"^(?:\d{1,3}[A-Z]?|[A-Z]{1,3}[-.]?\d{1,3}[A-Z]?)$",
    re.IGNORECASE,
)
# Header / legend tokens that match the mark shape but are not door numbers.
DOOR_MARK_STOPWORDS = frozenset(
    {
        "NO",
        "MARK",
        "TYPE",
        "SIZE",
        "WIDTH",
        "HGT",
        "HEIGHT",
        "HAND",
        "FIRE",
        "GL",
        "GLASS",
        "SEE",
        "ALL",
        "NEW",
        "EXISTING",
        "TYP",
        "EQ",
    }
)
# Glued mark + width: `01 3' - 6"` (also `A-1 3'-0"`).
DOOR_MARK_GLUED = re.compile(
    r"^((?:\d{1,3}[A-Z]?|[A-Z]{1,3}[-.]?\d{1,3}[A-Z]?))\s+(\d+\s*'\s*-?\s*\d+\s*\")$",
    re.IGNORECASE,
)
# Known materials are soft evidence — unknown codes still pass through as-is.
MATERIAL = re.compile(
    r"\b(HM|HMD|WD|AL|ALUM|ALUMINUM|STL|SS|MFR|HPL|PLAM|PLASTIC\s*LAM(?:INATE)?|"
    r"SC|FG|GL|GYP|WOOD)\b",
    re.IGNORECASE,
)
MATERIAL_CELL = re.compile(
    r"^(HM|HMD|WD|AL|ALUM|ALUMINUM|STL|SS|MFR|HPL|PLAM|SC|FG|GL|GYP|WOOD)$",
    re.IGNORECASE,
)
DIMENSION_CELL = re.compile(r"^\d+\s*'\s*-?\s*\d+\s*\"$")
INCH_DIMENSION_CELL = re.compile(r"^\d{2,3}\s*\"$")
STOREFRONT = re.compile(r"\b(STOREFRONT|ALUMINUM\s+STOREFRONT|FG-?\d+)\b", re.IGNORECASE)
SHEET_FINISH_NOTE = re.compile(
    r"ALL\s+HARDWARE\s+SHALL\s+BE\s+(US\d{1,2}[A-Z]?|\d{3})\b",
    re.IGNORECASE,
)

# Header tokens → column roles (FR-2 field set).
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "door_number": (
        "DOOR NO",
        "DOOR NO.",
        "OPENING NO",
        "OPENING NO.",
        "MARK NO",
        "MARK",
        "NUMBER",
        "NO.",
        "NO",
        "OPENING",
        "LEAF",
        "DOOR DESIG",
        "DESIGNATION",
    ),
    "room_name": ("ROOM NAME", "ROOM", "LOCATION"),
    "width": ("WIDTH", "WD", "W"),
    "height": ("HEIGHT", "HGT.", "HGT", "H"),
    "thickness": ("THICK", "THK", "THICKNESS"),
    "size": ("DOOR SIZE", "SIZE"),
    "door_type": ("DOOR TYPE", "TYPE", "DTYPE"),
    "frame_type": ("FRAME TYPE", "FTYPE"),
    "door_material": ("DOOR MATL", "DOOR MATERIAL", "DOOR MAT", "MAT'L", "MATL", "MAT."),
    "frame_material": ("FRAME MATL", "FRAME MATERIAL", "FRAME MAT", "FRAME"),
    "handing": ("HAND", "HANDING", "SWING"),
    "fire_rating": ("FIRE", "RATING", "LABEL", "FIRE RATING"),
    "finish": ("FINISH", "FIN"),
    "hardware_set": ("HARDWARE GROUP", "HW GROUP", "HW SET", "GROUP", "HDW"),
    # Not a bare "WALL": a "Wall/Floor Stop" column is hardware, and matching it
    # here handed `derive_frame_depths` a hardware value to look a throat up by.
    "wall_type": ("WALL TYPE", "WALL CONST", "PARTITION TYPE", "PARTITION"),
    "notes": ("DOOR NOTES", "NOTES", "REMARKS"),
    "detail": ("DETAIL", "DETAIL LOCATIONS", "DETAILS"),
}

# "EA." / "PR." / "SET" leading a cell marks a hardware legend line, not a door.
HARDWARE_QTY_LINE = re.compile(r"^(?:EA|PR|PAIR|SET|SETS)\.?(?:\s|$)", re.IGNORECASE)

MATRIX_HW_HEADERS = (
    "BUTTS",
    "HINGE",
    "LOCKS",
    "CLOSERS",
    "KICK",
    "THRESHOLD",
    "STOP",
    "HOLDER",
    "MISC",
    "MISCELLANEOUS",
    "PUSH",
    "PULL",
)


def _pdfrows():
    """Optional shared OCR / glyph repair (available when run inside the backend)."""
    try:
        from cbc.shared import pdfrows as module

        return module
    except ImportError:
        return None


def _normalize_material(raw: str | None) -> str | None:
    if not raw:
        return None
    token = re.sub(r"\s+", "", raw.strip().upper())
    mapping = {
        "ALUM": "AL",
        "ALUMINUM": "AL",
        "PLASTICLAM": "HPL",
        "PLASTICLAMINATE": "HPL",
        "PLAM": "HPL",
    }
    return mapping.get(token, token)


def inches_to_feet_inches(total_inches: int) -> str:
    feet, inches = divmod(int(total_inches), 12)
    return f"{feet}'-{inches}\""


def _open(pdf_path: str) -> fitz.Document:
    path = Path(pdf_path)
    if not path.exists():
        sys.exit(f"PDF not found: {pdf_path}")
    return fitz.open(path)


def to_display_space(page: fitz.Page, words: list[tuple]) -> list[tuple]:
    """Map unrotated mediabox word boxes into page.rect / viewer space.

    Same contract as `cbc.shared.pdfrows.to_display_space`. On rotation 270,
    clustering raw y buckets columns instead of rows.
    """
    if not page.rotation:
        return words
    matrix = page.rotation_matrix
    moved = []
    for word in words:
        box = (fitz.Rect(word[:4]) * matrix).normalize()
        moved.append((box.x0, box.y0, box.x1, box.y1, *word[4:]))
    return moved


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
    return [
        round(min(w[0] for w in words), 2),
        round(min(w[1] for w in words), 2),
        round(max(w[2] for w in words), 2),
        round(max(w[3] for w in words), 2),
    ]


def page_size(pdf_path: str, page_number: int) -> dict[str, float]:
    doc = _open(pdf_path)
    try:
        rect = doc[page_number - 1].rect
        return {"width": round(rect.width, 2), "height": round(rect.height, 2)}
    finally:
        doc.close()


def cluster_rows(
    pdf_path: str, page_number: int, region: list[float] | None = None
) -> list[dict[str, Any]]:
    """Cluster a page's positioned words into rows of cells (display space)."""
    doc = _open(pdf_path)
    pdfrows = _pdfrows()
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            sys.exit(f"page {page_number} out of range (1-{doc.page_count})")
        page = doc[index]
        shift = pdfrows.detect_shift(doc, pdf_path) if pdfrows else 0
        raw_words = list(page.get_text("words") or [])
        if shift and pdfrows:
            raw_words = [
                (*w[:4], pdfrows.shift_text(w[4], shift), *w[5:]) for w in raw_words
            ]
        words = to_display_space(page, raw_words)
        size = {"width": round(page.rect.width, 2), "height": round(page.rect.height, 2)}
        page_text = page.get_text()
        if shift and pdfrows:
            page_text = pdfrows.shift_text(page_text, shift)

        # Architectural body fonts are often outlined: title extracts, rows do not.
        # Fall back to OCR word boxes so retail inch-layout schedules still parse.
        if pdfrows and (
            not words
            or pdfrows.text_looks_like_schedule_title_only(page_text, len(words))
        ):
            ocr_words = pdfrows.ocr_words(page, dpi=300)
            if len(ocr_words) > len(words):
                words = ocr_words
                ocr_text = " ".join(w[4] for w in ocr_words)
                if ocr_text.strip():
                    page_text = f"{page_text}\n{ocr_text}" if page_text else ocr_text
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
                "_page_text": page_text,
            }
        )
    return rows


def parse_size(text: str) -> dict[str, Any]:
    """Resolve 4-digit, feet-inches, or inch-only WIDTH×HGT into width/height."""
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
    # Inch-only pair: first two distinct inch tokens (WIDTH then HGT).
    inch_hits = [int(v) for v in SIZE_INCHES.findall(text)]
    # Prefer door-like sizes (18–96") and take the first width/height pair.
    inch_hits = [v for v in inch_hits if 18 <= v <= 120]
    if len(inch_hits) >= 2:
        width_in, height_in = inch_hits[0], inch_hits[1]
        wf, wi = divmod(width_in, 12)
        hf, hi = divmod(height_in, 12)
        size_code = None
        if wi < 10 and hi < 10 and 2 <= wf <= 9 and 4 <= hf <= 9:
            size_code = f"{wf}{wi}{hf}{hi}"
        return {
            "size": size_code,
            "width": inches_to_feet_inches(width_in),
            "height": inches_to_feet_inches(height_in),
            "notation": "inches",
        }
    return {"size": None, "width": None, "height": None, "notation": None}


def normalize_handing(raw: str | None) -> str | None:
    if not raw:
        return None
    token = re.sub(r"[.\s]+", "", raw.upper())
    mapping = {
        "LHR": "LHR",
        "RHR": "RHR",
        "LH": "LH",
        "RH": "RH",
        "LEFTHAND": "LH",
        "RIGHTHAND": "RH",
        "LEFTHANDREVERSE": "LHR",
        "RIGHTHANDREVERSE": "RHR",
    }
    return mapping.get(token)


def normalize_fire_rating(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip().upper()
    if re.search(r"N/?R|NON[-\s]?RATED|UNRATED", text):
        return "NR"
    if re.search(r"(?:1|ONE)\s*(?:HR|HOUR)", text):
        return "60"
    match = re.search(r"(20|45|60|90|180)", text)
    return match.group(1) if match else None


def highlight_bbox(row: dict[str, Any]) -> list[float] | None:
    cells, boxes = row.get("cells") or [], row.get("cell_boxes") or []
    if not boxes or len(cells) != len(boxes):
        return row.get("bbox")

    anchors = [
        i
        for i, cell in enumerate(cells)
        if SIZE_EXPLICIT.search(cell)
        or SIZE_4DIGIT.search(cell)
        or INCH_DIMENSION_CELL.match(str(cell).strip())
        or HW_GROUP.search(cell)
        or DOOR_MARK_CELL.match(str(cell).strip())
    ]
    if not anchors:
        return row.get("bbox")

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


def _is_door_mark(cell: str | None) -> bool:
    text = str(cell or "").strip()
    if not text or not DOOR_MARK_CELL.match(text):
        return False
    if text.upper() in DOOR_MARK_STOPWORDS:
        return False
    # Reject bare glass/lite tags like GL-2 when they are the only "mark".
    if re.fullmatch(r"GL-?\d+[A-Z]?", text, re.IGNORECASE):
        return False
    return True


def _split_glued_mark_cell(cell: str) -> tuple[str, str] | None:
    """Return (mark, width) when a cell is `01 3' - 6"`, else None."""
    match = DOOR_MARK_GLUED.match(str(cell).strip())
    if not match:
        return None
    mark = match.group(1)
    if not _is_door_mark(mark):
        return None
    return mark, match.group(2)


def _door_number_from_row(row: dict[str, Any]) -> str | None:
    """Only accept a bare mark cell (e.g. `2`, `01`, `101A`, `A-1`) — never a dimension."""
    cells = row.get("cells") or []
    for cell in cells[:4]:
        cell_text = str(cell).strip()
        if DIMENSION_CELL.match(cell_text) or INCH_DIMENSION_CELL.match(cell_text):
            continue
        if _is_door_mark(cell_text):
            return cell_text
        glued = _split_glued_mark_cell(cell_text)
        if glued:
            return glued[0]
    return None


def _cells_with_split_mark(cells: list[str]) -> list[str]:
    """Expand a glued first cell so downstream column inference sees mark | width."""
    if not cells:
        return cells
    glued = _split_glued_mark_cell(cells[0])
    if not glued:
        return cells
    return [glued[0], glued[1], *cells[1:]]


def _alias_matches(alias: str, cell: str) -> bool:
    """Whether a header cell names this column.

    A short alias must be the whole cell. `height` carries the alias "H" and the
    match was a substring test, so "H" in "WIDTH" was true and `height` claimed
    the width column - every opening on that sheet came back square, 3030 for a
    3'-0" x 7'-0" door, with nothing to say it was wrong.
    """
    if len(alias) <= 2:
        return alias == cell
    return alias == cell or alias in cell


def _detect_header_map(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Map FR-2 field names to a cell index, and to where the column sits.

    The index alone is not enough. A schedule header is often stacked in tiers:

        ROOM          SIZE                 REMARKS
        DOOR   HDW   GLAZ  TYPE  MATL  TYPE  MATL  GLASS
        MARK   WD    HGT   THK   GROUP TYPE

    The best single row here is the bottom tier, which carries no ROOM cell
    because ROOM sits a tier above it. Its data rows do have a room column, so
    every field from WD onwards was read one cell to the left: `width` came back
    "VESTIBULE", `height` came back the width, and the thickness came back the
    height. Nothing flagged it, because every cell held a plausible value.

    So the x-range of each header word is recorded alongside its index. A column
    is read by where it sits on the sheet - which is how it is read by eye - and
    not by how many cells happen to precede it.
    """
    best: dict[str, int] = {}
    best_x: dict[str, tuple[float, float]] = {}
    best_hits = 0
    best_y = 0.0
    for row in rows[:40]:
        cells = [str(c).strip().upper() for c in (row.get("cells") or [])]
        joined = " ".join(cells)
        boxes = row.get("cell_boxes") or []
        mapping: dict[str, int] = {}
        spans: dict[str, tuple[float, float]] = {}
        for index, cell in enumerate(cells):
            for field, aliases in HEADER_ALIASES.items():
                if field in mapping:
                    continue
                if any(_alias_matches(alias, cell) for alias in aliases):
                    mapping[field] = index
                    if index < len(boxes) and len(boxes[index]) >= 3:
                        spans[field] = (float(boxes[index][0]), float(boxes[index][2]))
        # A row that names four columns is a header whatever it calls its first
        # one. Gating on DOOR / MARK / NO alone threw away the best header on a
        # schedule whose mark column is headed NUMBER - which contains no "NO" -
        # leaving a six-cell fragment to map the sheet, and every opening on it
        # was measured against the wrong columns.
        if len(mapping) < 4 and not (
            "DOOR" in joined or "MARK" in joined or "NO" in joined
        ):
            continue
        # Hardware-matrix schedules name butts/locks instead of GROUP.
        matrix_hits = sum(
            1 for cell in cells if any(h in cell for h in MATRIX_HW_HEADERS)
        )
        hits = len(mapping) + (1 if matrix_hits >= 2 else 0)
        if hits > best_hits:
            best_hits = hits
            best = mapping
            best_x = spans
            best_y = float(row.get("y") or 0)
            best["_matrix"] = 1 if matrix_hits >= 2 else 0  # type: ignore[assignment]
    if best_x:
        _fill_from_neighbouring_tiers(rows, best, best_x, best_y)
        best["_x"] = best_x  # type: ignore[assignment]
    return best


def _fill_from_neighbouring_tiers(
    rows: list[dict[str, Any]],
    best: dict[str, int],
    best_x: dict[str, tuple[float, float]],
    best_y: float,
) -> None:
    """Add columns the winning header row did not name, from the tiers beside it.

    A stacked header spreads its labels over several rows, and only one of them
    can win. On the sheet this was written for, ROOM sits a tier above the row
    that names WD / HGT / THK, so `room_name` came back null for every opening
    even though the column was right there.

    Additive only: a field the winning row named is never overridden, and a
    column whose x-range overlaps one already claimed is skipped. That second
    rule is what keeps a group label off a real column - "SIZE" spanning
    WD / HGT / THK, or "FRAME" spanning the frame columns, both land on top of
    something already mapped and are dropped rather than competing with it.
    """
    nearby = sorted(
        (row for row in rows[:40] if abs(float(row.get("y") or 0) - best_y) <= 30),
        key=lambda row: abs(float(row.get("y") or 0) - best_y),
    )
    claimed: list[tuple[float, float]] = list(best_x.values())
    for row in nearby:
        cells = [str(c).strip().upper() for c in (row.get("cells") or [])]
        boxes = row.get("cell_boxes") or []
        if len(boxes) != len(cells):
            continue
        for index, cell in enumerate(cells):
            if len(boxes[index]) < 3:
                continue
            span = (float(boxes[index][0]), float(boxes[index][2]))
            if any(min(span[1], c[1]) - max(span[0], c[0]) > 0 for c in claimed):
                continue
            for field, aliases in HEADER_ALIASES.items():
                if field in best:
                    continue
                if any(_alias_matches(alias, cell) for alias in aliases):
                    best[field] = index
                    best_x[field] = span
                    claimed.append(span)
                    break


def _header_confidence(header_map: dict[str, int] | None) -> int:
    """How many distinct FR-2 columns the header mapped (excludes _matrix flag)."""
    if not header_map:
        return 0
    indexes = [
        value
        for key, value in header_map.items()
        if key != "_matrix" and isinstance(value, int)
    ]
    # Collapsed maps that pin every field to column 0 are not usable.
    if indexes and len(set(indexes)) == 1 and len(indexes) > 1:
        return 0
    return len(indexes)


def _cell_looks_like_size(cell: str | None) -> bool:
    text = (cell or "").strip()
    if not text:
        return False
    return bool(
        SIZE_EXPLICIT.search(text)
        or INCH_DIMENSION_CELL.match(text)
        or SIZE_4DIGIT.search(text)
        or SIZE_INCHES.search(text)
    )


def _room_name(cell: str | None) -> str | None:
    """A room name, or None when the cell plainly holds something else.

    On a sheet whose general notes interleave with the schedule the header map
    lands `room_name` on the comments column, and every opening came back named
    "CARD READER IN; FREE EGRESS OUT; STOREROOM FUNCTION LOCKSET...". A room is
    called VESTIBULE or STAFF WASHROOM - it is short and it is not a sentence.
    """
    text = (cell or "").strip()
    if not text or len(text) > 40:
        return None
    if ";" in text or ". " in text:
        return None
    return text


def _cell(row: dict[str, Any], header_map: dict[str, int], field: str) -> str | None:
    # Reject collapsed header maps that pinned every field to column 0.
    indexes = [v for k, v in header_map.items() if k != "_matrix" and isinstance(v, int)]
    if indexes and len(set(indexes)) == 1 and len(indexes) > 2:
        return None

    cells = row.get("cells") or []

    # Prefer where the column sits over how many cells precede it. A stacked
    # header tier has fewer cells than its data rows, and matching by index then
    # reads every field one column to the left - plausibly, and silently.
    span = (header_map.get("_x") or {}).get(field) if isinstance(
        header_map.get("_x"), dict
    ) else None
    boxes = row.get("cell_boxes") or []
    if span and len(boxes) == len(cells):
        best_index, best_overlap = None, 0.0
        for index, box in enumerate(boxes):
            if len(box) < 3:
                continue
            overlap = min(span[1], float(box[2])) - max(span[0], float(box[0]))
            if overlap > best_overlap:
                best_index, best_overlap = index, overlap
        if best_index is not None:
            text = str(cells[best_index]).strip()
            return text or None
        # The column exists on the header and no cell reaches it: this row has
        # nothing in it. That is a blank, not a reason to fall back to an index
        # that would name a different column's value.
        return None

    index = header_map.get(field)
    if index is None or not isinstance(index, int) or index >= len(cells):
        return None
    text = str(cells[index]).strip()
    return text or None


def _row_is_opening(row: dict[str, Any], header_map: dict[str, int] | None = None) -> bool:
    """True only for real schedule opening rows — not elevation dimensions."""
    door_no = _door_number_from_row(row)
    if not door_no:
        return False
    cells = _cells_with_split_mark([str(c).strip() for c in (row.get("cells") or [])])
    # A hardware legend often shares the sheet with the schedule, and its lines
    # read as "3 | EA. | US10B | HAGER" - a quantity where the mark belongs and a
    # finish where the material does. Eleven of them came back as openings on one
    # sheet, each with a quantity for a door number. The legend is read by
    # `hardware_groups`, which is where those parts belong.
    #
    # Every cell, not just the leading ones: a glued mark splits back out and
    # pushes the "EA." along the row. The notes column is exempt, because a
    # remark may legitimately read "PROVIDE 2 EA. SILENCERS".
    notes_index = header_map.get("notes") if header_map else None
    if any(
        HARDWARE_QTY_LINE.match(cell)
        for index, cell in enumerate(cells)
        if index != notes_index
    ):
        return False
    # Mark must be an early cell (left side of the schedule).
    if not any(
        _is_door_mark(c) or _split_glued_mark_cell(c) for c in cells[:3]
    ):
        return False

    text = row.get("text", "")
    explicit_sizes = SIZE_EXPLICIT.findall(text)
    inch_sizes = [
        int(v) for v in SIZE_INCHES.findall(text) if 18 <= int(v) <= 120
    ]
    has_two_sizes = len(explicit_sizes) >= 2
    has_two_inch_sizes = len(inch_sizes) >= 2
    has_4digit = bool(SIZE_4DIGIT.search(text))
    has_group = bool(HW_GROUP.search(text))
    # Through `_cell`, which bounds-checks the index. Indexing `cells` directly
    # raised IndexError on any row shorter than the header - and a schedule has
    # plenty: title bands, notes, and the blank tail of a merged cell. The seed
    # caught that exception, skipped the sheet, and took a single stray row off a
    # lesser page as the take-off, so four real openings never left the PDF.
    hardware_cell = _cell(row, header_map, "hardware_set") if header_map else None
    has_bare_group = bool(hardware_cell and HW_GROUP_BARE.match(hardware_cell))
    has_material = any(MATERIAL.search(c) for c in cells)
    has_type_letter = any(re.fullmatch(r"[A-Z]", c) for c in cells[1:10])
    # Unknown material codes (not in whitelist) still count when header maps matl.
    header_mat = (
        _cell(row, header_map, "door_material") if header_map else None
    )
    has_any_matl = has_material or bool(header_mat)

    # Header-driven: mark + mapped WIDTH/HGT — material whitelist optional.
    if header_map and _header_confidence(header_map) >= 3:
        width_cell = _cell(row, header_map, "width")
        height_cell = _cell(row, header_map, "height")
        if _cell_looks_like_size(width_cell) and _cell_looks_like_size(height_cell):
            return True

    # GROUP-style: size + hardware group.
    if has_two_sizes and (has_group or has_bare_group):
        return True
    # Four-digit shorthand alone is too weak — phone fragments like
    # `314.578.4953` match SIZE_4DIGIT. Require a material or type letter too.
    if has_4digit and not has_two_sizes and (
        has_group
        or has_bare_group
        or has_any_matl
        or has_type_letter
    ):
        return True
    # Hardware-matrix: mark + W + H (+ optional type/material).
    if has_two_sizes and (
        (header_map and header_map.get("_matrix"))
        or has_any_matl
        or has_type_letter
        or has_group
        or has_bare_group
    ):
        return True
    # Inch-layout: mark + WIDTH" + HGT" (+ material / type / HW when present).
    if has_two_inch_sizes and (
        has_any_matl or has_type_letter or has_bare_group or has_group
    ):
        return True
    # Soft: two sizes + mark when a header mapped door_number (unknown materials OK).
    if (has_two_sizes or has_two_inch_sizes) and header_map and isinstance(
        header_map.get("door_number"), int
    ):
        return True
    return False


def _page_sheet_finish(page_text: str | None) -> str | None:
    if not page_text:
        return None
    match = SHEET_FINISH_NOTE.search(page_text)
    return match.group(1).upper() if match else None


def _infer_matrix_fields(cells: list[str]) -> dict[str, str]:
    """Column-order fallback for hardware-matrix and retail inch-layout schedules.

    Typical matrix: mark | room | width | height | thick | type | door matl | frame matl | X…
    Retail inch: mark | width\" | height\" | door matl | type | frame matl | frame type | HW | notes
    """
    cells = _cells_with_split_mark([str(c).strip() for c in cells])
    if not cells or not _is_door_mark(cells[0]):
        return {}
    out: dict[str, str] = {"door_number": cells[0]}
    i = 1
    if i < len(cells) and re.fullmatch(r"[A-Za-z][A-Za-z /-]{1,20}", cells[i]):
        out["room_name"] = cells[i]
        i += 1
    sizes: list[str] = []
    while i < len(cells) and len(sizes) < 2:
        if SIZE_EXPLICIT.search(cells[i]) or INCH_DIMENSION_CELL.match(cells[i]):
            sizes.append(cells[i])
            i += 1
        else:
            break
    if len(sizes) >= 2:
        # Normalise inch-only cells through parse_size so width/height are feet-inches.
        rebuilt = parse_size(f"{sizes[0]} {sizes[1]}")
        out["width"] = rebuilt["width"] or sizes[0]
        out["height"] = rebuilt["height"] or sizes[1]
        if rebuilt.get("size"):
            out["size"] = rebuilt["size"]
    if i < len(cells) and re.search(r"\d\s*\d/\d\"|3/4\"|1\s*3/4", cells[i]):
        out["thickness"] = cells[i].strip()
        i += 1
    # Door material may precede type on HPL / ALUM retail sheets.
    if i < len(cells) and MATERIAL_CELL.match(cells[i]):
        out["door_material"] = _normalize_material(cells[i]) or cells[i].upper()
        i += 1
    if i < len(cells) and re.fullmatch(r"[A-Z]", cells[i].strip()):
        out["door_type"] = cells[i].strip()
        i += 1
    mats: list[str] = []
    while i < len(cells) and MATERIAL_CELL.match(cells[i]):
        mats.append(_normalize_material(cells[i]) or cells[i].strip().upper())
        i += 1
    if not mats and i < len(cells):
        found = MATERIAL.findall(cells[i])
        if found:
            mats = [_normalize_material(m) or m.upper() for m in found]
    if mats:
        out.setdefault("door_material", mats[0])
        if len(mats) > 1:
            out["frame_material"] = mats[1]
        elif "door_material" in out and mats and mats[0] != out["door_material"]:
            out["frame_material"] = mats[0]
    # Frame type like `E, 3'-4"` or bare `E`.
    if i < len(cells) and (
        re.fullmatch(r"[A-Z]", cells[i].strip())
        or re.match(r"^[A-Z]\s*,", cells[i].strip())
    ):
        out["frame_type"] = cells[i].strip()
        i += 1
    # Bare HW digits only after type/material evidence — never the thickness `1`
    # column on matrix sheets before butts/locks X marks.
    if (
        i < len(cells)
        and HW_GROUP_BARE.match(cells[i])
        and "hardware_set" not in out
        and (out.get("door_material") or out.get("door_type") or out.get("frame_material"))
        and not any(c.upper() == "X" for c in cells[i:])
    ):
        out["hardware_set"] = f"GROUP {cells[i].strip()}"
        i += 1
    elif i < len(cells) and HW_GROUP.search(cells[i]):
        out["hardware_set"] = f"GROUP {HW_GROUP.search(cells[i]).group(1)}"
        i += 1
    if i < len(cells):
        note = " ".join(cells[i:]).strip()
        if note:
            out["notes"] = note
    return out


def parse_opening(
    row: dict[str, Any],
    header_map: dict[str, int] | None = None,
    sheet_finish: str | None = None,
) -> dict[str, Any]:
    """Best-effort field extraction from one clustered row (FR-2 allowlist)."""
    header_map = header_map or {}
    text = row["text"]
    cells = _cells_with_split_mark([str(c).strip() for c in (row.get("cells") or [])])
    # Prefer header indices; column-order inference only when the header is weak.
    inferred = (
        {}
        if _header_confidence(header_map) >= 3
        else _infer_matrix_fields(cells)
    )
    size = parse_size(text)

    # A column headed WIDTH that does not hold a width is not the width column.
    # On a sheet whose general notes interleave with the schedule, the header
    # words scatter across a dozen y-bands and the map comes out wrong; the
    # mapped cell then beat the size parsed from the row itself, and the take-off
    # reported `height: "HM"` - a material - for a 7'-0" door.
    def _dimension(field: str) -> str | None:
        cell = _cell(row, header_map, field)
        return cell if _cell_looks_like_size(cell) else None

    width = _dimension("width") or inferred.get("width") or size["width"]
    height = _dimension("height") or inferred.get("height") or size["height"]
    # Header cells may still be bare inches (`36"`) — normalise through parse_size.
    if width and height:
        rebuilt = parse_size(f"{width} {height}")
        size = {**size, **{k: rebuilt[k] or size[k] for k in rebuilt}}
        if rebuilt["width"]:
            width = rebuilt["width"]
        if rebuilt["height"]:
            height = rebuilt["height"]

    handing_raw = _cell(row, header_map, "handing")
    handing_match = HANDING.search(handing_raw or text)
    handing = normalize_handing(handing_match.group(1) if handing_match else handing_raw)

    rating_raw = _cell(row, header_map, "fire_rating")
    rating_match = FIRE_RATING.search(rating_raw or text)
    fire_rating = normalize_fire_rating(
        rating_match.group(0) if rating_match else rating_raw
    )

    group = HW_GROUP.search((_cell(row, header_map, "hardware_set") or "") + " " + text)
    finish_match = FINISH.search((_cell(row, header_map, "finish") or "") + " " + text)
    finish = (finish_match.group(1) if finish_match else None) or sheet_finish

    door_type = (
        _cell(row, header_map, "door_type")
        or inferred.get("door_type")
    )
    if door_type and len(door_type) > 4 and not re.match(r"^[A-Z]\s*,", door_type):
        door_type = None

    frame_type = _cell(row, header_map, "frame_type") or inferred.get("frame_type")

    door_material = _normalize_material(
        _cell(row, header_map, "door_material") or inferred.get("door_material")
    )
    # Unknown material codes: keep the header/inferred cell as-is (do not drop).
    if not door_material:
        raw_mat = _cell(row, header_map, "door_material") or inferred.get("door_material")
        if raw_mat and not DIMENSION_CELL.match(raw_mat) and not INCH_DIMENSION_CELL.match(raw_mat):
            door_material = raw_mat.strip().upper()
    frame_material = _normalize_material(
        _cell(row, header_map, "frame_material") or inferred.get("frame_material")
    )
    if not frame_material:
        raw_frame = _cell(row, header_map, "frame_material") or inferred.get("frame_material")
        if raw_frame and not DIMENSION_CELL.match(raw_frame) and not INCH_DIMENSION_CELL.match(
            raw_frame
        ):
            frame_material = raw_frame.strip().upper()
    if not door_material:
        materials = MATERIAL.findall(text)
        # Skip false hits inside notes
        if materials:
            door_material = _normalize_material(materials[0])
            if len(materials) > 1:
                frame_material = frame_material or _normalize_material(materials[1])

    hardware_set = f"GROUP {group.group(1)}" if group else None
    if not hardware_set:
        hw_cell = _cell(row, header_map, "hardware_set")
        if hw_cell and HW_GROUP_BARE.match(hw_cell.strip()):
            hardware_set = f"GROUP {hw_cell.strip()}"
        else:
            hardware_set = inferred.get("hardware_set")

    room_name = _room_name(_cell(row, header_map, "room_name")) or inferred.get("room_name")
    notes_parts = []
    thick = _cell(row, header_map, "thickness") or inferred.get("thickness")
    if thick:
        notes_parts.append(f"Thickness: {thick}")
    elif re.search(r"1\s*3/4\"", text):
        notes_parts.append('Thickness: 1 3/4"')
    for field in ("notes", "detail"):
        value = _cell(row, header_map, field) or (
            inferred.get("notes") if field == "notes" else None
        )
        if value and value not in notes_parts:
            notes_parts.append(value)

    is_matrix = bool(header_map.get("_matrix")) or (
        sum(1 for c in cells if c.upper() == "X") >= 2
    )
    matrix_marks = sum(1 for cell in cells if cell.upper() == "X")

    door_number = (
        _cell(row, header_map, "door_number")
        or inferred.get("door_number")
        or _door_number_from_row(row)
    )
    if door_number and not _is_door_mark(str(door_number)):
        # Header mapped the wrong column (e.g. thickness / notes) — re-scan the row.
        door_number = _door_number_from_row(row) or inferred.get("door_number")
        if door_number and not _is_door_mark(str(door_number)):
            door_number = None
    description = None
    if room_name and door_type:
        description = f"{room_name} — Type {door_type}"
    elif room_name:
        description = room_name
    elif door_type:
        description = f"Type {door_type}"

    opening: dict[str, Any] = {
        "door_number": door_number,
        "description": description,
        "room_name": room_name,
        "size": size["size"] or inferred.get("size"),
        "width": width or size["width"],
        "height": height or size["height"],
        "size_notation": size["notation"],
        "handing": handing,
        "fire_rating": fire_rating,
        "finish": finish.upper() if isinstance(finish, str) else finish,
        "hardware_set": hardware_set,
        "door_type": door_type,
        "frame_type": frame_type,
        "door_material": door_material,
        "frame_material": frame_material,
        "notes": "; ".join(notes_parts) if notes_parts else None,
        "source_page": row["source_page"],
        "page_size": row.get("page_size"),
        "bbox": highlight_bbox(row),
        "row_bbox": row.get("bbox"),
        "cell_boxes": row.get("cell_boxes"),
        "raw_row": text,
        "qty": 1,
    }

    flags: list[str] = []
    for field in ("fire_rating", "handing", "finish"):
        if opening[field] is None:
            flags.append(f"{field}_missing")
    if hardware_set is None and not (is_matrix and matrix_marks):
        flags.append("hardware_set_missing")
    elif hardware_set is None and is_matrix:
        flags.append("hardware_matrix_unexpanded")
        opening["evidence_note"] = (
            "Hardware-matrix schedule (X columns). Expand butts/locks/closers "
            "from the legend into `hardware` — do not invent a GROUP id."
        )

    if STOREFRONT.search(text) or (
        (door_material or "").upper() == "AL"
        and (frame_material or "").upper() == "AL"
    ):
        flags.append("out_of_scope_storefront")
        opening["evidence_note"] = (
            (opening.get("evidence_note") + " " if opening.get("evidence_note") else "")
            + "Aluminum/storefront opening — record under out_of_scope_items; "
            "CBC does not quote storefront (Matrix 2.3)."
        ).strip()

    if opening["handing"] is None:
        opening["evidence_note"] = (
            (opening.get("evidence_note") + " " if opening.get("evidence_note") else "")
            + "Handing not on this schedule row — resolve from floor-plan swing "
            "(Matrix 7.4) before leaving handing_missing."
        ).strip()

    if opening["fire_rating"] is None:
        opening["evidence_note"] = (
            (opening.get("evidence_note") + " " if opening.get("evidence_note") else "")
            + "Fire rating not on this row — check door/frame type schedule and "
            "Div 08 notes (Matrix 7.3 pending); flag, do not invent."
        ).strip()

    opening["flags"] = flags
    opening["confidence"] = round(max(0.3, 1.0 - 0.12 * len(flags)), 2)
    return opening


def _schedule_band(
    rows: list[dict[str, Any]], header_map: dict[str, int] | None = None
) -> tuple[float, float] | None:
    """Optional y-range hint around the door schedule table.

    Prefer a header carrying ROOM NAME / DOOR SIZE. Ignore 'DOOR SCHEDULE NOTES'
    titles — those sit in the notes column and truncate the real table.

    Skip banding when multiple header-like rows exist or the header map is weak —
    tall multi-table sheets drop openings under a tight band.
    """
    if header_map is not None and _header_confidence(header_map) < 3:
        return None
    header_y = None
    header_hits = 0
    for row in rows:
        cells = " ".join(str(c).upper() for c in (row.get("cells") or []))
        text = row.get("text", "").upper()
        if "DOOR SCHEDULE NOTES" in text:
            continue
        if "ROOM NAME" in cells or ("ROOM" in cells and "FRAME" in cells and "DOOR" in cells):
            header_hits += 1
            if header_y is None:
                header_y = row["y"]
        elif any(
            token in cells
            for token in ("WIDTH", "HGT", "HARDWARE GROUP", "DOOR NO", "OPENING NO")
        ):
            header_hits += 1
            if header_y is None:
                header_y = row["y"]
    if header_hits >= 2:
        return None
    if header_y is None:
        for row in rows:
            text = row.get("text", "").upper().strip()
            if text.startswith("DOOR SCHEDULE") and "NOTES" not in text:
                header_y = row["y"]
                break
    if header_y is None:
        return None
    # Openings may sit above or below the title on rotated / tall sheets.
    return (header_y - 120.0, header_y + 900.0)


def _openings_from_row(
    row: dict[str, Any],
    header_map: dict[str, int],
    sheet_finish: str | None,
) -> list[dict[str, Any]]:
    """One clustered row may hold one opening — or a merged pair on CAD sheets."""
    raw_cells = [str(c).strip() for c in (row.get("cells") or [])]
    raw_boxes = list(row.get("cell_boxes") or [])
    glued = _split_glued_mark_cell(raw_cells[0]) if raw_cells else None
    if glued:
        cells = [glued[0], glued[1], *raw_cells[1:]]
        if raw_boxes and len(raw_boxes) == len(raw_cells):
            # Keep the glued cell's box for both mark and width; rematch still
            # uses the row span, and highlight_bbox tightens to size/hw cells.
            boxes = [raw_boxes[0], raw_boxes[0], *raw_boxes[1:]]
        else:
            boxes = raw_boxes
        row = {**row, "cells": cells, "cell_boxes": boxes or row.get("cell_boxes")}
    else:
        cells = raw_cells

    # Locate mark anchors: glued `03 3'-0"`, bare mark + room, or early mark with
    # sizes. Mid-row frame-type digits must not steal a real opening mark.
    anchors: list[int] = []
    for i, cell in enumerate(cells):
        glued = _split_glued_mark_cell(cell)
        if glued:
            anchors.append(i)
            continue
        if not _is_door_mark(cell):
            continue
        nxt = cells[i + 1] if i + 1 < len(cells) else ""
        if re.fullmatch(r"[A-Za-z][A-Za-z /-]{1,20}", nxt):
            anchors.append(i)
        elif i == 0 and (
            len(SIZE_EXPLICIT.findall(row.get("text", ""))) >= 2
            or len([v for v in SIZE_INCHES.findall(row.get("text", "")) if 18 <= int(v) <= 120])
            >= 2
        ):
            anchors.append(i)
        elif i <= 2 and (
            len(SIZE_EXPLICIT.findall(row.get("text", ""))) >= 2
            or HW_GROUP.search(row.get("text", ""))
        ):
            # Mark in an early cell even when a noise token precedes it.
            anchors.append(i)
    # Prefer the leftmost mark; drop later bare digits (frame types).
    if anchors:
        first = min(anchors)
        anchors = [a for a in anchors if a == first or (a - first) > 3]
    if anchors and 0 in anchors and any(a > 0 for a in anchors):
        anchors = [0]
    # One mark on the row means one opening, so there is nothing to slice apart.
    # Slicing from the mark threw away every column to its left, and on a
    # schedule headed ROOM NAME | NUMBER | ... that is the room: `room_name` came
    # back null for every opening on the sheet while the name sat in cell 0.
    if len(anchors) == 1:
        anchors = [0]
    if not anchors and _row_is_opening(row, header_map):
        return [parse_opening(row, header_map, sheet_finish=sheet_finish)]
    if not anchors:
        return []

    results = []
    for ai, start in enumerate(anchors):
        end = anchors[ai + 1] if ai + 1 < len(anchors) else len(cells)
        slice_cells = cells[start:end]
        slice_boxes = (row.get("cell_boxes") or [])[start:end]
        if len(slice_cells) < 3:
            continue
        sub = {
            **row,
            "cells": slice_cells,
            "cell_boxes": slice_boxes or row.get("cell_boxes"),
            "text": " | ".join(slice_cells),
            "bbox": (
                [
                    round(min(b[0] for b in slice_boxes), 2),
                    round(min(b[1] for b in slice_boxes), 2),
                    round(max(b[2] for b in slice_boxes), 2),
                    round(max(b[3] for b in slice_boxes), 2),
                ]
                if slice_boxes and len(slice_boxes) == len(slice_cells)
                else row.get("bbox")
            ),
        }
        if not _row_is_opening(sub, header_map) and not (
            _is_door_mark(slice_cells[0])
            and (
                len(SIZE_EXPLICIT.findall(sub["text"])) >= 2
                or len(
                    [v for v in SIZE_INCHES.findall(sub["text"]) if 18 <= int(v) <= 120]
                )
                >= 2
            )
        ):
            continue
        opening = parse_opening(sub, header_map, sheet_finish=sheet_finish)
        # Drop fragment parses with no room/type/material/size on a matrix sheet.
        if not any(
            opening.get(k)
            for k in ("room_name", "door_type", "door_material", "hardware_set", "size", "width")
        ):
            continue
        results.append(opening)
    return results


def schedule_rows(pdf_path: str, page_number: int) -> list[dict[str, Any]]:
    """Rows that describe an opening, with FR-2 fields filled when present."""
    rows = cluster_rows(pdf_path, page_number)
    header_map = _detect_header_map(rows)
    sheet_finish = _page_sheet_finish(rows[0].get("_page_text") if rows else None)
    band = _schedule_band(rows, header_map)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        page_text = row.pop("_page_text", None)
        if page_text and not sheet_finish:
            sheet_finish = _page_sheet_finish(page_text)
        if band and not (band[0] <= row["y"] <= band[1]):
            cells = row.get("cells") or []
            strong = (
                len(SIZE_EXPLICIT.findall(row.get("text", ""))) >= 2
                or len(SIZE_INCHES.findall(row.get("text", ""))) >= 2
            ) and (
                any(MATERIAL.search(str(c)) for c in cells)
                or _row_is_opening(row, header_map)
            )
            if not strong:
                continue
        for opening in _openings_from_row(row, header_map, sheet_finish):
            mark = str(opening.get("door_number") or "")
            if not mark or mark in seen:
                continue
            if not any(
                opening.get(k)
                for k in ("room_name", "door_type", "door_material", "hardware_set", "size", "width")
            ):
                continue
            seen.add(mark)
            out.append(opening)
    # Prefer numeric mark order when marks are integers.
    def _sort_key(o: dict[str, Any]) -> tuple:
        m = str(o.get("door_number") or "")
        return (0, int(m)) if m.isdigit() else (1, m)

    out.sort(key=_sort_key)
    return out


def openings_envelope(
    pdf_path: str, page_number: int, source_file: str | None = None
) -> dict[str, Any]:
    openings = schedule_rows(pdf_path, page_number)
    # Per opening, not only on the envelope. `geometry.measure_bboxes` has to
    # reopen the sheet to measure a row, and it picks the PDF by the opening's
    # own `source_file`. With more than one file in uploads/raw and none named,
    # it cannot tell which - so it drops the box on every opening and the
    # estimator gets a schedule whose rows highlight nothing.
    if source_file:
        for opening in openings:
            opening.setdefault("source_file", source_file)
    out_of_scope = [
        {
            "door_number": o.get("door_number"),
            "reason": "aluminum_storefront",
            "raw_row": o.get("raw_row"),
            "source_page": o.get("source_page"),
        }
        for o in openings
        if "out_of_scope_storefront" in (o.get("flags") or [])
    ]
    # Estimators still want to *see* storefront rows, but they must not become
    # quote line items. Keep them in openings with the flag; also list them.
    return {
        "source_file": source_file,
        "source_page": page_number,
        "openings": openings,
        "out_of_scope_items": out_of_scope or None,
    }


def _demo() -> None:
    assert parse_size("3070")["width"] == "3'-0\""
    assert parse_size("3070")["height"] == "7'-0\""
    assert parse_size("3670")["width"] == "3'-6\""
    explicit = parse_size("01 3' - 6\" | 7' - 0\" | A")
    assert explicit["width"] == "3'-6\"" and explicit["height"] == "7'-0\""
    assert normalize_handing("L.H.") == "LH"
    assert normalize_handing("LHR") == "LHR"
    assert normalize_fire_rating("90 MIN") == "90"
    assert normalize_fire_rating("NON-RATED") == "NR"

    row = {
        "source_page": 14,
        "text": "01 3' - 6\" | 7' - 0\" | A | 1 | TEMP. HM HMD | GROUP 1",
        "page_size": {"width": 2592.0, "height": 1728.0},
        "bbox": [640.2, 609.8, 998.4, 619.1],
        "cells": ["01", "3' - 6\"", "7' - 0\"", "A", "1", "TEMP. HM HMD", "GROUP 1"],
        "cell_boxes": [[640.2, 609.8, 690.0, 619.1]] * 7,
    }
    opening = parse_opening(row)
    assert opening["door_number"] == "01"
    assert opening["hardware_set"] == "GROUP 1"
    assert opening["fire_rating"] is None
    assert "fire_rating_missing" in opening["flags"]

    matrix = {
        "source_page": 19,
        "text": "2 | DINING | 6'-0\" | 7'-0\" | 1 | 3/4\" | B | AL | AL | X | X | 10/A6.1 | 8, 10",
        "page_size": {"width": 2448.0, "height": 1584.0},
        "bbox": [1185.0, 959.0, 2130.0, 972.0],
        "cells": [
            "2",
            "DINING",
            "6'-0\"",
            "7'-0\"",
            "1",
            "3/4\"",
            "B",
            "AL",
            "AL",
            "X",
            "X",
            "10/A6.1",
            "8, 10",
        ],
        "cell_boxes": [[0, 0, 1, 1]] * 13,
    }
    header = {
        "door_number": 0,
        "room_name": 1,
        "width": 2,
        "height": 3,
        "door_type": 6,
        "door_material": 7,
        "frame_material": 8,
        "_matrix": 1,
    }
    m = parse_opening(matrix, header, sheet_finish="US32D")
    assert m["door_number"] == "2"
    assert m["size"] == "6070"
    assert m["finish"] == "US32D"
    assert "out_of_scope_storefront" in m["flags"]
    assert m["hardware_set"] is None
    assert "hardware_matrix_unexpanded" in m["flags"]

    # Retail / architectural-font schedule: inch WIDTH×HGT, HPL, ALUM, bare HW digit.
    retail = {
        "source_page": 3,
        "text": '1 | 36" | 84" | HPL | C | ALUM | E, 3\'-4" | 5 | DOOR PRE-HUNG IN FRAME',
        "page_size": {"width": 1200.0, "height": 800.0},
        "bbox": [10, 20, 400, 30],
        "cells": [
            "1",
            '36"',
            '84"',
            "HPL",
            "C",
            "ALUM",
            "E, 3'-4\"",
            "5",
            "DOOR PRE-HUNG IN FRAME",
        ],
        "cell_boxes": [[0, 0, 1, 1]] * 9,
    }
    retail_header = {
        "door_number": 0,
        "width": 1,
        "height": 2,
        "door_material": 3,
        "door_type": 4,
        "frame_material": 5,
        "frame_type": 6,
        "hardware_set": 7,
        "notes": 8,
    }
    assert _row_is_opening(retail, retail_header)
    r = parse_opening(retail, retail_header)
    assert r["door_number"] == "1"
    assert r["width"] == "3'-0\""
    assert r["height"] == "7'-0\""
    assert r["size"] == "3070"
    assert r["size_notation"] == "inches"
    assert r["door_material"] == "HPL"
    assert r["frame_material"] == "AL"
    assert r["door_type"] == "C"
    assert r["hardware_set"] == "GROUP 5"
    assert "out_of_scope_storefront" not in (r.get("flags") or [])
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

    if args.openings:
        payload = openings_envelope(args.pdf, args.page, source_file=args.pdf)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for item in payload["openings"]:
                print(item.get("raw_row"))
        return 0

    payload = cluster_rows(args.pdf, args.page)
    if args.json:
        clean = [{k: v for k, v in row.items() if k != "_page_text"} for row in payload]
        print(json.dumps(clean, indent=2))
    else:
        for item in payload:
            print(item.get("text"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
