#!/usr/bin/env python3
"""Extract door / frame / hardware schedules from an architectural PDF.

Architectural sheets are CAD exports with no reliable table ruling. Rows are
recovered by clustering positioned words on the y-axis in *display* space
(after applying page.rotation_matrix). Without that transform, 270°-rotated
sheets (most of a typical bid set) cluster columns as rows and return zero
openings — which is what broke the Taco Bell Endeavor 2.0 take-off.

Verified against:
  - Dutch Bros fixture (upright, GROUP-style schedule)
  - Taco Bell Endeavor 2.0 A1.1 (rotated 270°, hardware-matrix schedule)

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
    "HARDWARE GROUPS",
    "HARDWARE SCHEDULE",
    "WINDOW SCHEDULE",
    "FINISH SCHEDULE",
]

# FR-2 / Matrix 7.1 — 4-digit shorthand or explicit feet-inches.
SIZE_4DIGIT = re.compile(r"\b([2-9])([0-9])([4-9])([0-9])\b")
SIZE_EXPLICIT = re.compile(r"(\d+)\s*'\s*-?\s*(\d+)\s*\"")
# Matrix 7.4 — prefer reverse forms first so LHR wins over LH.
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
HW_GROUP = re.compile(r"\b(?:GROUP|HW|HDW|HG)[\s-]*(\d+)\b", re.IGNORECASE)
FINISH = re.compile(r"\b(US\d{1,2}[A-Z]?|6\d{2})\b")
# Single-digit marks appear on retail chain schedules (Taco Bell 1–6).
# Never treat a dimension like 12'-1" as a mark — require a bare cell.
DOOR_MARK_CELL = re.compile(r"^\d{1,3}[A-Z]?$")
# Dutch Bros (and similar) glue mark + width: `01 3' - 6"`.
DOOR_MARK_GLUED = re.compile(
    r"^(\d{1,3}[A-Z]?)\s+(\d+\s*'\s*-?\s*\d+\s*\")$",
    re.IGNORECASE,
)
MATERIAL = re.compile(r"\b(HM|HMD|WD|AL|STL|SS|MFR)\b", re.IGNORECASE)
DIMENSION_CELL = re.compile(r"^\d+\s*'\s*-?\s*\d+\s*\"$")
STOREFRONT = re.compile(r"\b(STOREFRONT|ALUMINUM\s+STOREFRONT|FG-?\d+)\b", re.IGNORECASE)
SHEET_FINISH_NOTE = re.compile(
    r"ALL\s+HARDWARE\s+SHALL\s+BE\s+(US\d{1,2}[A-Z]?|\d{3})\b",
    re.IGNORECASE,
)

# Header tokens → column roles (FR-2 field set).
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "door_number": ("DOOR NO", "DOOR NO.", "MARK", "NO.", "NO", "OPENING"),
    "room_name": ("ROOM NAME", "ROOM", "LOCATION"),
    "width": ("WIDTH", "W"),
    "height": ("HEIGHT", "H"),
    "thickness": ("THICK", "THK", "THICKNESS"),
    "size": ("DOOR SIZE", "SIZE"),
    "door_type": ("DOOR TYPE", "TYPE", "DTYPE"),
    "frame_type": ("FRAME TYPE", "FTYPE"),
    "door_material": ("DOOR MATL", "DOOR MATERIAL", "DOOR MAT"),
    "frame_material": ("FRAME MATL", "FRAME MATERIAL", "FRAME MAT", "FRAME"),
    "handing": ("HAND", "HANDING", "SWING"),
    "fire_rating": ("FIRE", "RATING", "LABEL", "FIRE RATING"),
    "finish": ("FINISH", "FIN"),
    "hardware_set": ("HARDWARE GROUP", "HW GROUP", "HW SET", "GROUP", "HDW"),
    "wall_type": ("WALL TYPE", "WALL", "PARTITION"),
    "notes": ("DOOR NOTES", "NOTES", "REMARKS"),
    "detail": ("DETAIL", "DETAIL LOCATIONS", "DETAILS"),
}

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
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            sys.exit(f"page {page_number} out of range (1-{doc.page_count})")
        page = doc[index]
        words = to_display_space(page, page.get_text("words"))
        size = {"width": round(page.rect.width, 2), "height": round(page.rect.height, 2)}
        page_text = page.get_text()
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


def _split_glued_mark_cell(cell: str) -> tuple[str, str] | None:
    """Return (mark, width) when a cell is `01 3' - 6"`, else None."""
    match = DOOR_MARK_GLUED.match(str(cell).strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _door_number_from_row(row: dict[str, Any]) -> str | None:
    """Only accept a bare mark cell (e.g. `2`, `01`, `101A`) — never a dimension."""
    cells = row.get("cells") or []
    for cell in cells[:4]:
        cell_text = str(cell).strip()
        if DIMENSION_CELL.match(cell_text):
            continue
        if DOOR_MARK_CELL.match(cell_text):
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


def _detect_header_map(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Map FR-2 field names → cell index from a header-like row."""
    best: dict[str, int] = {}
    best_hits = 0
    for row in rows[:40]:
        cells = [str(c).strip().upper() for c in (row.get("cells") or [])]
        joined = " ".join(cells)
        if "DOOR" not in joined and "MARK" not in joined and "NO" not in joined:
            continue
        mapping: dict[str, int] = {}
        for index, cell in enumerate(cells):
            for field, aliases in HEADER_ALIASES.items():
                if field in mapping:
                    continue
                if any(alias == cell or alias in cell for alias in aliases):
                    mapping[field] = index
        # Hardware-matrix schedules name butts/locks instead of GROUP.
        matrix_hits = sum(
            1 for cell in cells if any(h in cell for h in MATRIX_HW_HEADERS)
        )
        hits = len(mapping) + (1 if matrix_hits >= 2 else 0)
        if hits > best_hits:
            best_hits = hits
            best = mapping
            best["_matrix"] = 1 if matrix_hits >= 2 else 0  # type: ignore[assignment]
    return best


def _cell(row: dict[str, Any], header_map: dict[str, int], field: str) -> str | None:
    # Reject collapsed header maps that pinned every field to column 0.
    indexes = [v for k, v in header_map.items() if k != "_matrix" and isinstance(v, int)]
    if indexes and len(set(indexes)) == 1 and len(indexes) > 2:
        return None
    index = header_map.get(field)
    cells = row.get("cells") or []
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
    # Mark must be an early cell (left side of the schedule).
    if not any(
        DOOR_MARK_CELL.match(c) or _split_glued_mark_cell(c) for c in cells[:3]
    ):
        return False

    text = row.get("text", "")
    explicit_sizes = SIZE_EXPLICIT.findall(text)
    has_two_sizes = len(explicit_sizes) >= 2
    has_4digit = bool(SIZE_4DIGIT.search(text))
    has_group = bool(HW_GROUP.search(text))

    # GROUP-style (Dutch Bros): size + hardware group.
    if has_two_sizes and has_group:
        return True
    # Four-digit shorthand alone is too weak — phone fragments like
    # `314.578.4953` match SIZE_4DIGIT. Require a material or type letter too.
    if has_4digit and not has_two_sizes and (
        has_group
        or any(MATERIAL.search(c) for c in cells)
        or any(re.fullmatch(r"[A-Z]", c) for c in cells[1:8])
    ):
        return True
    # Hardware-matrix (Taco Bell A1.1): mark + W + H (+ optional type/material).
    if has_two_sizes and (
        (header_map and header_map.get("_matrix"))
        or any(MATERIAL.search(c) for c in cells)
        or any(re.fullmatch(r"[A-Z]", c) for c in cells[2:10])
    ):
        return True
    return False


def _page_sheet_finish(page_text: str | None) -> str | None:
    if not page_text:
        return None
    match = SHEET_FINISH_NOTE.search(page_text)
    return match.group(1).upper() if match else None


def _infer_matrix_fields(cells: list[str]) -> dict[str, str]:
    """Column-order fallback for hardware-matrix schedules (Taco Bell A1.1 style).

    Typical order: mark | room | width | height | thick | type | door matl | frame matl | X…
    """
    cells = _cells_with_split_mark([str(c).strip() for c in cells])
    if not cells or not DOOR_MARK_CELL.match(cells[0]):
        return {}
    out: dict[str, str] = {"door_number": cells[0]}
    i = 1
    if i < len(cells) and re.fullmatch(r"[A-Za-z][A-Za-z /-]{1,20}", cells[i]):
        out["room_name"] = cells[i]
        i += 1
    sizes: list[str] = []
    while i < len(cells) and len(sizes) < 2:
        if SIZE_EXPLICIT.search(cells[i]):
            sizes.append(cells[i])
            i += 1
        else:
            break
    if len(sizes) >= 2:
        out["width"], out["height"] = sizes[0], sizes[1]
    if i < len(cells) and re.search(r"\d\s*\d/\d\"|3/4\"|1\s*3/4", cells[i]):
        out["thickness"] = cells[i].strip()
        i += 1
    if i < len(cells) and re.fullmatch(r"[A-Z]", cells[i].strip()):
        out["door_type"] = cells[i].strip()
        i += 1
    mats: list[str] = []
    while i < len(cells) and re.fullmatch(r"AL|HM|HMD|WD|STL|SS|MFR", cells[i].strip(), re.I):
        mats.append(cells[i].strip().upper())
        i += 1
    if not mats and i < len(cells):
        found = MATERIAL.findall(cells[i])
        if found:
            mats = [m.upper() for m in found]
    if mats:
        out["door_material"] = mats[0]
        if len(mats) > 1:
            out["frame_material"] = mats[1]
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
    inferred = _infer_matrix_fields(cells) if header_map.get("_matrix") or True else {}
    size = parse_size(text)

    width = (
        _cell(row, header_map, "width")
        or inferred.get("width")
        or size["width"]
    )
    height = (
        _cell(row, header_map, "height")
        or inferred.get("height")
        or size["height"]
    )
    if width and height and not size["size"]:
        rebuilt = parse_size(f"{width} {height}")
        size = {**size, **{k: rebuilt[k] or size[k] for k in rebuilt}}

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

    door_type = _cell(row, header_map, "door_type") or inferred.get("door_type")
    if door_type and len(door_type) > 4:
        door_type = None

    door_material = (
        _cell(row, header_map, "door_material") or inferred.get("door_material")
    )
    frame_material = (
        _cell(row, header_map, "frame_material") or inferred.get("frame_material")
    )
    if not door_material:
        materials = MATERIAL.findall(text)
        # Skip false hits inside notes
        if materials:
            door_material = materials[0].upper()
            if len(materials) > 1:
                frame_material = frame_material or materials[1].upper()

    room_name = _cell(row, header_map, "room_name") or inferred.get("room_name")
    notes_parts = []
    thick = _cell(row, header_map, "thickness") or inferred.get("thickness")
    if thick:
        notes_parts.append(f"Thickness: {thick}")
    elif re.search(r"1\s*3/4\"", text):
        notes_parts.append('Thickness: 1 3/4"')
    for field in ("notes", "detail"):
        value = _cell(row, header_map, field)
        if value:
            notes_parts.append(value)

    is_matrix = bool(header_map.get("_matrix")) or (
        sum(1 for c in cells if c.upper() == "X") >= 2
    )
    matrix_marks = sum(1 for cell in cells if cell.upper() == "X")
    hardware_set = f"GROUP {group.group(1)}" if group else None

    door_number = (
        _cell(row, header_map, "door_number")
        or inferred.get("door_number")
        or _door_number_from_row(row)
    )
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
        "size": size["size"],
        "width": width or size["width"],
        "height": height or size["height"],
        "size_notation": size["notation"],
        "handing": handing,
        "fire_rating": fire_rating,
        "finish": finish.upper() if isinstance(finish, str) else finish,
        "hardware_set": hardware_set,
        "door_type": door_type,
        "door_material": door_material.upper() if door_material else None,
        "frame_material": frame_material.upper() if frame_material else None,
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


def _schedule_band(rows: list[dict[str, Any]]) -> tuple[float, float] | None:
    """Optional y-range hint around the door schedule table.

    Prefer a header carrying ROOM NAME / DOOR SIZE. Ignore 'DOOR SCHEDULE NOTES'
    titles — those sit in the notes column and truncate the real table.
    """
    header_y = None
    for row in rows:
        cells = " ".join(str(c).upper() for c in (row.get("cells") or []))
        text = row.get("text", "").upper()
        if "DOOR SCHEDULE NOTES" in text:
            continue
        if "ROOM NAME" in cells or ("ROOM" in cells and "FRAME" in cells and "DOOR" in cells):
            header_y = row["y"]
            break
    if header_y is None:
        for row in rows:
            text = row.get("text", "").upper().strip()
            if text.startswith("DOOR SCHEDULE") and "NOTES" not in text:
                header_y = row["y"]
                break
    if header_y is None:
        return None
    # Openings may sit above or below the title on rotated sheets.
    return (header_y - 80.0, header_y + 420.0)


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

    # Locate mark+room anchors: <mark> followed within 1 cell by a room-like token,
    # or mark at index 0 with sizes (GROUP-style).
    anchors: list[int] = []
    for i, cell in enumerate(cells):
        if not DOOR_MARK_CELL.match(cell):
            continue
        nxt = cells[i + 1] if i + 1 < len(cells) else ""
        if re.fullmatch(r"[A-Za-z][A-Za-z /-]{1,20}", nxt):
            anchors.append(i)
        elif i == 0 and len(SIZE_EXPLICIT.findall(row.get("text", ""))) >= 2:
            anchors.append(i)
    # A frame-type digit mid-row (Dutch Bros `… | C | 2 | HM HMD | …`) must not
    # steal the row from a real mark already at column 0.
    if anchors and 0 in anchors and any(a > 0 for a in anchors):
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
            DOOR_MARK_CELL.match(slice_cells[0])
            and len(SIZE_EXPLICIT.findall(sub["text"])) >= 2
        ):
            continue
        opening = parse_opening(sub, header_map, sheet_finish=sheet_finish)
        # Drop fragment parses with no room/type on a matrix sheet.
        if not opening.get("room_name") and not opening.get("door_type"):
            continue
        results.append(opening)
    return results


def schedule_rows(pdf_path: str, page_number: int) -> list[dict[str, Any]]:
    """Rows that describe an opening, with FR-2 fields filled when present."""
    rows = cluster_rows(pdf_path, page_number)
    header_map = _detect_header_map(rows)
    sheet_finish = _page_sheet_finish(rows[0].get("_page_text") if rows else None)
    band = _schedule_band(rows)

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
                and any(MATERIAL.search(str(c)) for c in cells)
            )
            if not strong:
                continue
        for opening in _openings_from_row(row, header_map, sheet_finish):
            mark = str(opening.get("door_number") or "")
            if not mark or mark in seen:
                continue
            if not any(
                opening.get(k)
                for k in ("room_name", "door_type", "door_material", "hardware_set", "size")
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
