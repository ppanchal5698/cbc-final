"""Read the hardware-set legend off a drawing sheet, deterministically.

A door schedule cites a hardware group per opening - `07`, `08`, `12` - and the
legend that says what those groups *contain* was never parsed by anything.
`HW_GROUP` in `parse_schedule` matches the callout on an opening row and stops
there. So groups were recorded as referenced and never itemised, and every
manufacturer part on the sheet stayed inside the PDF: two different bid sets
reached pricing with zero Hager parts and a row of blank MANUAL lines, which is
also why the special-net sheet could never be exercised.

Two things make this sheet harder than the door schedule, and only one of them
is real:

1. **The page is rotated** - `page.rotation` is 270 on these sheets, so raw
   `get_text("words")` reads the table sideways and the text comes out as
   `HAGER HAGER HAGER HAGER`. That is not a column-major table, it is an
   unrotated one. `pdfrows.rows_from_words` applies `to_display_space` first,
   which is the whole reason it exists, and the rows come out ordinary.

2. **Sets are laid out in columns side by side**, so one display row crosses two
   or three sets: `... CODE LOCKS | GC | SET 05 - CLOSET DOOR | 1 1/2 PR. HINGES
   | BB1279 ...`. Cells are bucketed by x into column bands before anything is
   read as a sequence. This one is real, and it is what the banding is for.

What it will not do is guess. A cell it cannot classify stays in `raw_row`, the
field stays null and the item carries a flag - the same contract the door-schedule
parser holds: never silently wrong.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cbc.shared import pdfrows

# "SET 01 - EXTERIOR STOREFRONT", "SET 03A – REAR SERVICE", "GROUP 7: RESTROOM"
SET_HEADER = re.compile(
    r"\b(?:SET|GROUP|HW\s*SET|HARDWARE\s+(?:SET|GROUP))\s*#?\s*([0-9]{1,3}[A-Z]?)\s*[-–—:]\s*(.*)",
    re.I,
)
# A header with no dash, at the end of a cell: "... | SET 07"
SET_BARE = re.compile(r"\b(?:SET|GROUP)\s*#?\s*([0-9]{1,3}[A-Z]?)\s*$", re.I)

QTY = re.compile(r"^\s*(\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*")
# No trailing \b: "EA." is followed by a space, and `.` to ` ` is not a word
# boundary, so the engine backtracked to "EA" and left the dot heading the
# description as ". STOREROOM".
UNIT = re.compile(r"\b(EA|PR|PAIR|SET)\.?", re.I)

# US10B, 26D, 626, 26D / 626, MIL, ALUMINUM, PRIME COAT
FINISH = re.compile(
    r"^(?:(?:US\s?\d{1,2}[A-Z]?|\d{3}|\d{2}[A-Z])"
    r"(?:\s*/\s*(?:US\s?\d{1,2}[A-Z]?|\d{3}|\d{2}[A-Z]))?"
    r"|MILL?|ML|CL|CLR|ALUMINUM|ALUM\.?|BRASS|WHITE|DBRZ|PRIME\s+COAT(?:\s+NGP)?)$",
    re.I,
)
SUPPLIER = re.compile(r"^(LL|GC|OWNER|TENANT|WIB)$", re.I)

_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")

# Recognised so a cell can be *identified*, never so one can be invented: an
# unknown vendor leaves `manufacturer` null and flags the item.
KNOWN_MANUFACTURERS = {
    "HAGER": "Hager", "NGP": "NGP", "NATIONAL GUARD": "National Guard",
    "PEMKO": "Pemko", "ROCKWOOD": "Rockwood", "IVES": "IVES", "FALCON": "Falcon",
    "SCHLAGE": "Schlage", "VON DUPRIN": "Von Duprin", "LCN": "LCN", "ZERO": "Zero",
    "ADAMS RITE": "Adams Rite", "ROTON": "Roton", "CODE LOCKS": "Code Locks",
    "EDWARDS": "Edwards", "BEA": "BEA", "BEA GROUP": "BEA", "HORTON": "Horton",
    "GLYNN JOHNSON": "Glynn Johnson", "GLY": "Glynn Johnson", "CRL": "CRL",
    "DON JO": "Don-Jo", "MICOM": "Micom", "CAL ROYAL": "Cal-Royal",
    "ALARM LOCK": "Alarm Lock", "TRIMCO": "Trimco", "BOBRICK": "Bobrick",
    "ASI": "ASI", "BRADLEY": "Bradley", "GAMCO": "Gamco", "NUDO": "Nudo",
    "WORLD DRYER": "World Dryer", "MARLITE": "Marlite", "SARGENT": "Sargent",
    "CORBIN": "Corbin", "YALE": "Yale", "BEST": "Best", "STANLEY": "Stanley",
    "MCKINNEY": "McKinney", "TUBELITE": "Tubelite",
    # How the Dutch Bros prototype sheets spell it. Mapped so the Allegion gate
    # still sees a Von Duprin device; an unrecognised name would let it be priced
    # off a list.
    "VON DURPIN": "Von Duprin",
}

LEGEND_MARKERS = (
    "HARDWARE SET", "HARDWARE GROUP", "HARDWARE SCHEDULE", "HW SCHEDULE",
    "FINISH HARDWARE", "DOOR HARDWARE",
)

# Two set columns sit ~435pt apart on the sheets seen so far. Narrow enough to
# catch a tighter layout, wide enough not to split one set down the middle.
COLUMN_GAP = 200.0
# Used only for the rightmost column when there is no next column to bound it.
DEFAULT_COLUMN_WIDTH = 450.0


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def find_legend_pages(pdf: Path) -> list[int]:
    """1-indexed pages that name a hardware legend."""
    import fitz

    doc = fitz.open(pdf)
    try:
        return [
            index + 1
            for index in range(doc.page_count)
            if any(marker in doc[index].get_text().upper() for marker in LEGEND_MARKERS)
        ]
    finally:
        doc.close()


def _column_bands(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """(left, right) of each set column, taken from where the SET headers sit.

    Anchoring on headers rather than on whitespace is what makes this stable: a
    legend's body rows wrap unpredictably, but every column starts with a header
    and the headers line up.

    The right edge matters as much as the left. Without one, the rightmost column
    ran to the edge of the sheet and swallowed the title block and the general
    notes - "PROJECT NO:", "17037", "PROVIDE LEFT HANDED OPERATION" all arrived as
    hardware items. On a real sheet the legend sits at x 407-1277 and that noise
    starts at x 1907, so bounding each column at the next one's left edge (and the
    last at one column's width) separates them cleanly.
    """
    starts = sorted(
        float(box[0])
        for row in rows
        for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or [])
        if SET_HEADER.search(_text(cell)) or SET_BARE.search(_text(cell))
    )
    if not starts:
        return []
    lefts = [starts[0]]
    for value in starts[1:]:
        if value - lefts[-1] >= COLUMN_GAP:
            lefts.append(value)

    gaps = [b - a for a, b in zip(lefts, lefts[1:])]
    width = min(gaps) if gaps else DEFAULT_COLUMN_WIDTH
    return [
        (left, lefts[index + 1] if index + 1 < len(lefts) else left + width)
        for index, left in enumerate(lefts)
    ]


def _band_of(x: float, bands: list[tuple[float, float]]) -> int | None:
    """Which column a cell belongs to, or None when it is outside the legend."""
    for index, (left, right) in enumerate(bands):
        if left - 1.0 <= x < right:
            return index
    return None


# `1/2`, `4-1/2`, `1 1/2` - a hinge dimension, not a part. Without this the
# `4 1/2" x 4 1/2"` in a hinge description offered `1/2` as the part number.
_MEASUREMENT = re.compile(r'^[\d\s/\-x×."\']+$')


def _looks_like_part(token: str) -> bool:
    """A part number carries a digit, is not a finish code, and is not a dimension.

    It need not carry a letter: Hager writes `3580`, `4501`, `5100`, `350`. That
    is also why position matters more than pattern here - `350` is a threshold
    part in one column and could pass for a finish in another.
    """
    text = token.strip(",;:()\"'")
    if len(text) < 2 or not _HAS_DIGIT.search(text):
        return False
    if _MEASUREMENT.match(text) and not text.isdigit():
        return False  # a fraction or a size, never a part
    return not FINISH.match(text.upper())


def classify_item(cells: list[str]) -> dict[str, Any]:
    """Pull one hardware line out of a legend row. Unsure fields stay null.

    These rows are positional - `qty | EA. description | part | finish |
    manufacturer | supplied_by` - so the manufacturer is the anchor: the cell
    before it is the finish and the one before that is the part. Reading purely
    by pattern instead got `350` (a Hager threshold) classified as a finish
    because it is three digits.
    """
    texts = [_text(cell) for cell in cells]
    item: dict[str, Any] = {
        "qty": None, "unit": None, "description": None, "part": None,
        "finish": None, "manufacturer": None, "supplied_by": None,
        "raw_row": " | ".join(t for t in texts if t), "flags": [],
    }

    taken: set[int] = set()
    for index, text in enumerate(texts):
        if not text:
            taken.add(index)
            continue
        upper = text.upper()
        if item["supplied_by"] is None and SUPPLIER.match(upper):
            item["supplied_by"] = upper.upper()
            taken.add(index)
        elif item["manufacturer"] is None and upper in KNOWN_MANUFACTURERS:
            item["manufacturer"] = KNOWN_MANUFACTURERS[upper]
            item["_mfr_at"] = index
            taken.add(index)

    anchor = item.pop("_mfr_at", None)
    if anchor is not None:
        # Walk left from the manufacturer: finish, then part. Once the finish is
        # claimed, the next cell left is the part *whatever it looks like* -
        # `350` is a Hager threshold and also three digits, so a pattern test
        # alone hands the part number to the finish field.
        for offset in (1, 2):
            index = anchor - offset
            if index < 0 or index in taken:
                continue
            text = texts[index]
            if not text:
                continue
            if item["finish"] is None and FINISH.match(text.upper()):
                item["finish"] = text
                taken.add(index)
                continue
            if item["part"] is None:
                head = text.split()[0]
                if _HAS_DIGIT.search(head) and len(head.strip(",;:()\"'")) >= 2:
                    item["part"] = head.strip(",;:()\"'")
                    rest = " ".join(text.split()[1:]).strip()
                    if rest:
                        item["description"] = rest
                    taken.add(index)

    prose: list[str] = []
    for index, text in enumerate(texts):
        if index in taken or not text:
            continue
        if item["qty"] is None:
            match = QTY.match(text)
            if match:
                item["qty"] = match.group(1).strip()
                text = text[match.end():].strip()
        unit = UNIT.search(text)
        if unit and item["unit"] is None:
            item["unit"] = unit.group(1).upper() + "."
            text = (text[: unit.start()] + " " + text[unit.end():]).strip()
        if text:
            prose.append(text)

    # A part may still be sitting inside the description ("CONCAVE WALL STOP 236W").
    for chunk in prose:
        if item["part"] is not None:
            break
        for token in chunk.split():
            if _looks_like_part(token):
                item["part"] = token.strip(",;:()\"'")
                break

    described = " ".join(prose).strip()
    if described:
        item["description"] = (
            described if not item["description"] else f"{described} {item['description']}"
        ).strip()

    for field, flag in (("part", "part_missing"), ("manufacturer", "manufacturer_missing"),
                        ("qty", "qty_missing")):
        if item[field] is None:
            item["flags"].append(flag)
    return item


def _is_item_row(cells: list[str]) -> bool:
    joined = " ".join(_text(c) for c in cells)
    return bool(joined) and bool(UNIT.search(joined) or QTY.match(joined))


# A legend drawn as one table - `#: | DESCRIPTION | MFR. | MODEL & FINISH` - with
# each group's name written vertically up a merged first column ("GROUP 1 - BACK
# DOOR"). No row holds a group header and no row carries a quantity or unit, so
# the column-of-sets reader above finds neither a set nor an item on it.
_DESCRIPTION_HEAD = re.compile(r"^DESCRIPTION\b", re.I)
_MFR_HEAD = re.compile(r"^(?:MFR|MFG|MANUFACTURER)\.?$", re.I)
_MODEL_HEAD = re.compile(r"^MODEL\b", re.I)
_LABEL_START = re.compile(r"^(?:SET|GROUP|HW)$", re.I)
_COUNT = re.compile(r"^\((\d+)\)\s*")  # "(3) 5BB1, 4.5, NRP, 626"
_COLUMN_TOLERANCE = 12.0
_LABEL_COLUMN_WIDTH = 40.0


def _matrix_header(rows: list[dict[str, Any]]) -> tuple[float, float, float] | None:
    """(header bottom, table left, table right) from the DESCRIPTION / MFR. / MODEL row.

    Only the outer edges are taken. Headers are centred over their columns and the
    values under them are left-aligned - MFR. sits 18pt right of the names below
    it - so a value is placed by its order in the row, not matched to a header x.
    """
    for row in rows:
        found: dict[str, list[float]] = {}
        for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or []):
            text = _text(cell)
            for key, pattern in (("desc", _DESCRIPTION_HEAD), ("mfr", _MFR_HEAD), ("model", _MODEL_HEAD)):
                if key not in found and pattern.match(text):
                    found[key] = [float(v) for v in box]
        if "desc" in found and "mfr" in found:
            bottom = max(box[3] for box in found.values())
            right = (found.get("model") or found["mfr"])[2]
            return bottom, found["desc"][0], right
    return None


def _vertical_labels(words: list[tuple], left: float, right: float, top: float) -> list[dict[str, Any]]:
    """Group names written up (or down) the first column, each with its y-span.

    A rotated label comes out of the text layer one word per box, so it is read by
    position: bottom to top, each SET / GROUP word starting a new label. Text
    turned the other way reads top to bottom, and is tried second.
    """
    column = [w for w in words if w[1] >= top and left <= (w[0] + w[2]) / 2 <= right]
    for ordered in (
        sorted(column, key=lambda w: -w[3]),
        sorted(column, key=lambda w: w[1]),
    ):
        labels: list[list[tuple]] = []
        for word in ordered:
            if _LABEL_START.match(str(word[4])):
                labels.append([word])
            elif labels:
                labels[-1].append(word)
        found = []
        for words_in in labels:
            header = SET_HEADER.search(" ".join(str(w[4]) for w in words_in))
            if header:
                found.append({
                    "set_id": header.group(1).upper(),
                    "specified": _text(header.group(2)) or None,
                    "top": min(w[1] for w in words_in),
                    "bottom": max(w[3] for w in words_in),
                    "bbox": pdfrows.union_bbox(words_in),
                })
        if found:
            return sorted(found, key=lambda label: label["top"])
    return []


def _split_by_labels(rows: list[tuple[float, float]], centers: list[float]) -> list[int] | None:
    """Split rows (top, bottom), in order, into len(centers) consecutive groups.

    A merged cell centres its label, so the split chosen is the one whose groups'
    middles sit nearest their labels. Splitting halfway between two labels is
    wrong whenever the groups differ in size: on the sheet that prompted this a
    nine-row group above a seven-row one put the boundary on the last row.
    """
    n, k = len(rows), len(centers)
    if not k or n < k:
        return None
    inf = float("inf")
    best = [[inf] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for j in range(1, k + 1):
        for end in range(j, n + 1):
            for start in range(j - 1, end):
                if best[j - 1][start] == inf:
                    continue
                middle = (rows[start][0] + rows[end - 1][1]) / 2
                cost = best[j - 1][start] + abs(middle - centers[j - 1])
                if cost < best[j][end]:
                    best[j][end], cut[j][end] = cost, start
    groups = [0] * n
    end = n
    for j in range(k, 0, -1):
        start = cut[j][end]
        for index in range(start, end):
            groups[index] = j - 1
        end = start
    return groups


def classify_matrix_item(description: str, manufacturer: str, model: str) -> dict[str, Any]:
    """One row of a DESCRIPTION | MFR. | MODEL & FINISH legend. Unsure fields stay null.

    The model cell leads with the part and ends with the finish - `700 83", 630`,
    `(3) 5BB1, 4.5, NRP, 626` - and a leading `(n)` is the only quantity it states.
    """
    upper = _text(manufacturer).upper()
    text = _text(model)
    qty = None
    count = _COUNT.match(text)
    if count:
        qty, text = count.group(1), text[count.end():]
    # "630. AT INTERIOR": a sentence's full stop is not part of the finish.
    tokens = [t.strip(",;:()") for t in text.replace(",", " ").split()]
    tokens = [t[:-1] if t.endswith(".") and t[:-1].isdigit() else t for t in tokens]
    head = tokens[0] if tokens else ""
    part = head if _HAS_DIGIT.search(head) and len(head) >= 2 else None
    finishes = [t for t in tokens[1:] if FINISH.match(t.upper())]
    item: dict[str, Any] = {
        "qty": qty, "unit": None, "description": _text(description) or None,
        "part": part, "finish": finishes[-1] if finishes else None,
        "manufacturer": KNOWN_MANUFACTURERS.get(upper),
        "supplied_by": None,
        "raw_row": " | ".join(t for t in (_text(description), _text(manufacturer), _text(model)) if t),
        "flags": [],
    }
    for field, flag in (("part", "part_missing"), ("manufacturer", "manufacturer_missing"),
                        ("qty", "qty_missing")):
        if item[field] is None:
            item["flags"].append(flag)
    return item


def _matrix_sets(
    rows: list[dict[str, Any]], words: list[tuple], page_number: int, page_size: dict[str, float]
) -> list[dict[str, Any]]:
    """Every group in a one-table legend whose group names run vertically."""
    header = _matrix_header(rows)
    if header is None:
        return []
    top, left, right = header

    items: list[tuple[float, float, dict[str, Any]]] = []
    for row in sorted(rows, key=lambda r: float(r.get("y") or 0.0)):
        y = float(row.get("y") or 0.0)
        if y <= top:
            continue
        # Description, manufacturer, model, in that order, between the table's
        # edges - the vertical group name to the left and the next drawing to the
        # right are outside them.
        inside = [
            (_text(cell), [float(v) for v in box])
            for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or [])
            if left - _COLUMN_TOLERANCE <= float(box[0]) < right and _text(cell)
        ]
        if len(inside) < 2:
            continue
        # The table has ended once the rows stop coming at its own pace.
        if len(items) >= 3:
            gaps = sorted(b[0] - a[0] for a, b in zip(items, items[1:]))
            if y - items[-1][0] > 3 * gaps[len(gaps) // 2]:
                break
        model = " ".join(text for text, _ in inside[2:])
        bottom = max(box[3] for _, box in inside)
        items.append((y, bottom, classify_matrix_item(inside[0][0], inside[1][0], model)))

    labels = _vertical_labels(words, left - _LABEL_COLUMN_WIDTH, left - 1.0, top)
    groups = _split_by_labels([(y, bottom) for y, bottom, _ in items], [
        (label["top"] + label["bottom"]) / 2 for label in labels
    ])
    if groups is None:
        return []

    sets: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        members = [entry for entry, group in zip(items, groups) if group == index]
        entry: dict[str, Any] = {
            "hardware_set": label["set_id"],
            "set_id": label["set_id"],
            "specified": label["specified"],
            "source_page": page_number,
            "page_size": page_size,
            "bbox": label["bbox"],
            "items": [item for _, _, item in members],
            "flags": [],
        }
        # The split is by position. If a group's rows do not straddle its label,
        # say so rather than hand over a confident wrong grouping.
        if members:
            middle = (members[0][0] + members[-1][1]) / 2
            row_height = (members[-1][1] - members[0][0]) / len(members)
            if abs(middle - (label["top"] + label["bottom"]) / 2) > row_height:
                entry["flags"].append("group_rows_uncertain")
        sets.append(entry)
    return sets


def _carries_information(item: dict[str, Any]) -> bool:
    """Whether a parsed row says anything an estimator could act on.

    A row that yields no part, no manufacturer and no unit is a wrapped fragment
    of the line above, not a hardware line of its own.
    """
    return any(item.get(field) for field in ("part", "manufacturer", "unit"))


def groups_on_page(pdf: Path, page_number: int) -> dict[str, Any]:
    """Every hardware set on one page, with its items."""
    import fitz

    doc = fitz.open(pdf)
    try:
        page = doc[page_number - 1]
        shift = pdfrows.detect_shift(doc, str(pdf))
        rows = pdfrows.rows_from_words(page, shift=shift)
        words = pdfrows.to_display_space(page, page.get_text("words"))
        if shift:
            words = [(*w[:4], pdfrows.shift_text(w[4], shift), *w[5:]) for w in words]
        page_size = {"width": round(page.rect.width, 2), "height": round(page.rect.height, 2)}
    finally:
        doc.close()

    sets = _column_sets(rows, _column_bands(rows), page_number, page_size)
    if not any(entry["items"] for entry in sets):
        # Nothing itemised: the legend may be one table with its group names
        # written vertically, which the column reader cannot see.
        sets = _matrix_sets(rows, words, page_number, page_size) or sets
    if not sets:
        return {
            "source_file": pdf.name,
            "source_page": page_number,
            "page_size": page_size,
            "sets": [],
            "no_legend_reason": "no SET / GROUP header on this page",
        }

    for entry in sets:
        if not entry["items"]:
            entry["flags"].append("no_items_read")

    return {
        "source_file": pdf.name,
        "source_page": page_number,
        "page_size": page_size,
        "sets": sets,
    }


def _column_sets(
    rows: list[dict[str, Any]],
    bands: list[tuple[float, float]],
    page_number: int,
    page_size: dict[str, float],
) -> list[dict[str, Any]]:
    """Sets laid out in columns side by side, each headed `SET 01 - ...`."""
    per_column: dict[int, list[tuple[float, list[str], list[Any]]]] = {
        index: [] for index in range(len(bands))
    }
    for row in rows:
        buckets: dict[int, tuple[list[str], list[Any]]] = {}
        for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or []):
            band = _band_of(float(box[0]), bands)
            if band is None:
                continue  # title block, general notes, revision stamp
            cells, boxes = buckets.setdefault(band, ([], []))
            cells.append(_text(cell))
            boxes.append(box)
        for band, (cells, boxes) in buckets.items():
            per_column[band].append((float(row.get("y") or 0.0), cells, boxes))

    sets: list[dict[str, Any]] = []
    for band in sorted(per_column):
        current: dict[str, Any] | None = None
        for _y, cells, boxes in sorted(per_column[band], key=lambda entry: entry[0]):
            joined = " | ".join(c for c in cells if c)
            header = SET_HEADER.search(joined)
            name = _text(header.group(2)) if header else None
            if header is None:
                header = SET_BARE.search(joined)
                name = None
            if header:
                current = {
                    "hardware_set": header.group(1).upper(),
                    "set_id": header.group(1).upper(),
                    "specified": name or None,
                    "source_page": page_number,
                    "page_size": page_size,
                    "bbox": [round(float(v), 2) for v in boxes[0]] if boxes else None,
                    "items": [],
                    "flags": [],
                }
                sets.append(current)
                continue
            if current is None or not _is_item_row(cells):
                continue
            item = classify_item(cells)
            if not _carries_information(item):
                # A wrapped finish that spilled onto its own row ("626", "D / 626")
                # is a fragment of the line above, not a line. `raw_row` on the
                # real item still holds the text, so nothing is lost by not
                # inventing an item around it.
                continue
            current["items"].append(item)
    return sets


def groups_envelope(pdf: Path, pages: list[int] | None = None) -> dict[str, Any]:
    """Every legend page merged into one artifact payload."""
    targets = pages or find_legend_pages(pdf)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_number in targets:
        for entry in groups_on_page(pdf, page_number).get("sets") or []:
            key = str(entry.get("hardware_set") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(entry)
    return {
        "source_file": pdf.name,
        "pages_read": list(targets),
        "sets": merged,
        "no_legend_reason": None if merged else "no hardware legend found on any page",
    }


def _demo() -> None:
    """Runnable check on the shapes, with no PDF required."""
    assert SET_HEADER.search("SET 03A – ENHANCED REAR SERVICE DOOR").group(1) == "03A"
    assert SET_HEADER.search("GROUP 7: RESTROOM").group(1) == "7"

    item = classify_item(["1", "EA. STOREROOM", "3580 26D WTN SFIC", "26D / 626", "HAGER", "GC"])
    assert (item["qty"], item["unit"], item["part"]) == ("1", "EA.", "3580"), item
    assert item["manufacturer"] == "Hager" and item["supplied_by"] == "GC", item

    hinge = classify_item(['1 1/2 EA. HINGES', 'BB1279 4 1/2" x 4 1/2"', "US10B", "HAGER", "GC"])
    assert hinge["qty"] == "1 1/2" and hinge["part"] == "BB1279", hinge
    assert hinge["finish"] == "US10B", hinge

    unknown = classify_item(["1", "EA. LOCK", "XX9", "26D", "WIDGETCO", "GC"])
    assert unknown["manufacturer"] is None
    assert "manufacturer_missing" in unknown["flags"]

    assert _column_bands([]) == []
    bands = [(68.0, 503.0), (503.0, 938.0), (938.0, 1373.0)]
    assert _band_of(940.0, bands) == 2
    assert _band_of(70.0, bands) == 0
    # The title block sits far to the right of the last column and is not hardware.
    assert _band_of(2324.0, bands) is None
    print("hardware_groups demo OK")


if __name__ == "__main__":
    _demo()
