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

# A set's name: `01`, `03A`, and the letter-led groups some legends use (`E1`
# exterior, `O2` office) - which a door schedule cites as written.
_SET_ID = r"([A-Z]?[0-9]{1,3}[A-Z]?)"
# Between the word and the number: `SET 01`, `SET: 01`, `GROUP NO. 02`, `GROUP #E1`.
_SET_NO = r"\s*(?:NO\.?|NUMBER|#)?\s*:?\s*#?\s*"
# "SET 01 - EXTERIOR STOREFRONT", "SET 03A – REAR SERVICE", "GROUP 7: RESTROOM", "GROUP #E1: VESTIBULE"
SET_HEADER = re.compile(
    r"\b(?:SET|GROUP|HW\s*SET|HARDWARE\s+(?:SET|GROUP))" + _SET_NO + _SET_ID + r"\s*[-–—:]\s*(.*)",
    re.I,
)
# A header with no dash, at the end of a cell: "... | SET 07", "HARDWARE SET: 01", "GROUP NO. 02"
SET_BARE = re.compile(r"\b(?:SET|GROUP)" + _SET_NO + _SET_ID + r"\s*$", re.I)

QTY = re.compile(r"^\s*(\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*")
# Ends at its dot or a word boundary. A bare `\b` after the dot fails ("EA." is
# followed by a space, and `.` to ` ` is not a boundary), which left the dot heading
# the description as ". STOREROOM"; no boundary at all read PRIVACY as PR + IVACY.
UNIT = re.compile(r"\b(EA|PR|PAIR|SET)(?:\.|\b)", re.I)

# US10B, 26D, 626, 26D / 626, MIL, ALUMINUM, PRIME COAT. The bare two-digit codes
# end in B or D (10B, 26D, 32D): `21J` is a Hager pull and `33E` a push plate.
FINISH = re.compile(
    r"^(?:(?:US\s?\d{1,2}[A-Z]?|\d{3}|\d{2}[BD])"
    r"(?:\s*/\s*(?:US\s?\d{1,2}[A-Z]?|\d{3}|\d{2}[BD]))?"
    r"|MILL?|ML|CL|CLR|ALUMINUM|ALUM\.?|ALM\.?|BRASS|WHITE|DBRZ|BK|BLK|PRIME\s+COAT(?:\s+NGP)?)$",
    re.I,
)
SUPPLIER = re.compile(r"^(LL|GC|OWNER|TENANT|WIB)$", re.I)
_BY_PARTY = re.compile(r"^BY\s+(?:THE\s+)?([A-Z][A-Z .&/\-]{2,40})$", re.I)

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
    "ALARM LOCK": "Alarm Lock", "ALARM CLOCK": "Alarm Lock", "TRIMCO": "Trimco", "BOBRICK": "Bobrick",
    "ASI": "ASI", "BRADLEY": "Bradley", "GAMCO": "Gamco", "NUDO": "Nudo",
    "WORLD DRYER": "World Dryer", "MARLITE": "Marlite", "SARGENT": "Sargent",
    "CORBIN": "Corbin", "YALE": "Yale", "BEST": "Best", "STANLEY": "Stanley",
    "MCKINNEY": "McKinney", "TUBELITE": "Tubelite",
    "DORMA": "Dorma", "DORMAKABA": "Dormakaba", "ARROW": "Arrow", "BALDWIN": "Baldwin",
    "BURNS": "Burns", "DETEX": "Detex", "SECURITRON": "Securitron", "DOR-O-MATIC": "Dor-O-Matic",
    "ABH": "ABH", "DCI": "DCI", "JACKNOB": "Jacknob", "LOCKNET": "Locknet", "PRECISION": "Precision",
    "KAWNEER": "Kawneer", "MONARCH": "Monarch", "ACCURATE": "Accurate", "DORMA KABA": "Dormakaba",
    # How the Dutch Bros prototype sheets spell it. Mapped so the Allegion gate
    # still sees a Von Duprin device; an unrecognised name would let it be priced
    # off a list.
    "VON DURPIN": "Von Duprin",
    "HAGER MFG": "Hager", "HID": "HID", "NORTON": "Norton",
    # The rest of CBC's phase 1 vendors (requirements 5.3): hand dryers, FRP, doors.
    "MARKAR": "Markar", "DYSON": "Dyson", "EXCEL DRYER": "Excel Dryer", "XLERATOR": "Excel Dryer",
    "FIVE LAKES": "Five Lakes", "PIONEER": "Pioneer", "MASONITE": "Masonite Architectural",
    "SPECIAL-LITE": "Special-Lite", "SPECIAL LITE": "Special-Lite", "HP FABRICATION": "HP Fabrication",
    "ALLEGION": "Allegion",
}
# The abbreviations a specification's hardware schedule writes in its maker
# column (`SCH`, `IVE`). Trusted only as a whole cell: in running text `DET` and
# `SEC` are a detail and a section, not Detex and Securitron.
ABBREVIATED_MANUFACTURERS = {
    "SCH": "Schlage", "IVE": "IVES", "VON": "Von Duprin", "ZER": "Zero", "FAL": "Falcon",
    "HES": "HES", "PEM": "Pemko", "HAG": "Hager", "SAR": "Sargent", "BES": "Best",
    "MCK": "McKinney", "TRI": "Trimco", "DET": "Detex", "SEC": "Securitron", "NOR": "Norton",
    "STANELY": "Stanley",  # as the Culver's prototype sheets spell it
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


# Symbol-font glyphs a spec prints as markers - a link to the cut sheet, an
# electrified opening - read out of the private-use area. They are no part, finish
# or word: the Evernorth strike's finish came back as "630" and was lost.
_PRIVATE_USE = re.compile("[-]")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", _PRIVATE_USE.sub(" ", str(value or ""))).strip()


def heading_counts(pdf: Path, pages: list[int]) -> dict[int, int]:
    """How many set headings each page holds - `SET 01 -`, `HARDWARE SET: 01`,
    `GROUP #E1:`. A page with one is a legend; a page that only mentions hardware
    (a spec book has dozens) has none."""
    import fitz

    doc = fitz.open(pdf)
    try:
        counts: dict[int, int] = {}
        for number in pages:
            if not 1 <= number <= doc.page_count:
                continue
            lines = [line.strip() for line in doc[number - 1].get_text().splitlines() if line.strip()]
            counts[number] = sum(1 for line in lines if TEXT_SET_HEADER.match(line) or SET_HEADER.search(line))
        return counts
    finally:
        doc.close()


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
    if '"' in token or "'" in token:
        return False  # `34"` and `18'` are sizes - stripped of the mark they look like parts
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
        elif item["supplied_by"] is None and _BY_PARTY.match(upper):
            # "BY SECURITY VENDOR" in the catalog column: someone else supplies it.
            item["supplied_by"] = _supplier(_BY_PARTY.match(upper).group(1))
            taken.add(index)
        elif item["manufacturer"] is None and (upper in KNOWN_MANUFACTURERS or upper in ABBREVIATED_MANUFACTURERS):
            item["manufacturer"] = KNOWN_MANUFACTURERS.get(upper) or ABBREVIATED_MANUFACTURERS[upper]
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
    """A count or a unit; or, on a row that states neither, a maker or a supplier in a
    cell of its own (`AUTOMATIC DOOR | 7100 - EASY ACCESS SURFACE | HORTON | GC`)."""
    texts = [_text(c) for c in cells]
    joined = " ".join(texts)
    if not joined:
        return False
    if UNIT.search(joined) or QTY.match(joined):
        return True
    return any(t.upper() in KNOWN_MANUFACTURERS or SUPPLIER.match(t) for t in texts if t)


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
    # A two-line label ("GROUP 3 -" beside "RESTROOM DOOR") is two runs of
    # rotated text side by side; read together they interleave. Each run of
    # text at one x is read on its own, and the labels from all of them kept.
    runs: list[list[tuple]] = []
    for word in sorted(column, key=lambda w: w[0]):
        if runs and abs(word[0] - runs[-1][0][0]) <= 4.0:
            runs[-1].append(word)
        else:
            runs.append([word])
    if len(runs) > 1:
        merged: dict[str, dict[str, Any]] = {}
        for run in runs:
            for label in _vertical_labels(run, left, right, top):
                merged.setdefault(label["set_id"], label)
        if merged:
            return sorted(merged.values(), key=lambda label: label["top"])
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
        item = classify_matrix_item(inside[0][0], inside[1][0], model)
        # This layout has no quantity column: `(3) 5BB1` is the only count it writes.
        assume_one_each(item)
        items.append((y, bottom, item))

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


# ── a legend drawn as a table under a header row ──────────────────────────────
# `GROUP # | DOOR | QTY | DESCRIPTION | CATALOG # | MFG`, repeated over each block
# of groups, two tables side by side (the Culver's prototype sheets). A group's
# number and doors start its first row; its name runs down the group column on
# the rows after; a note under it stands alone.

_HEAD_COLUMNS = (
    ("group", re.compile(r"^(?:HW\s*|HDW\s*)?(?:GROUP|SET|GRP)\s*(?:#|NO\.?)?$", re.I)),
    ("door", re.compile(r"^(?:DOORS?|OPENINGS?|OPNG\.?)\s*(?:#|NO\.?)?$", re.I)),
    ("qty", re.compile(r"^(?:QTY\.?|QUANTITY)$", re.I)),
    ("description", re.compile(r"^(?:DESCRIPTION|ITEM)$", re.I)),
    ("catalog", re.compile(r"^(?:CATALOG|CAT\.?|MODEL|PART|PRODUCT)\s*(?:#|NO\.?|NUMBER)?$", re.I)),
    ("finish", re.compile(r"^(?:FINISH|FIN\.?)$", re.I)),
    ("mfg", re.compile(r"^(?:MFG|MFR|MANUFACTURER|MANUF|MAKE)\.?$", re.I)),
)
_ROW_TOLERANCE = 6.0  # pt: one visual row the text layer split in two
_VALUE_REACH = 100.0  # pt: how far right of its header a column's values run
_VALUE_SLACK = 25.0  # pt: how far left of its header a value may start
_GROUP_ID = re.compile(r"^\s*([A-Z]?[0-9]{1,3}[A-Z]?)\s*$", re.I)


def _table_headers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every table header: its row's y, each column's x, and the table's x-range.
    A row with two QTY columns holds two tables side by side."""
    tables: list[dict[str, Any]] = []
    for row in rows:
        named: list[tuple[str, float]] = []
        for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or []):
            text = _text(cell)
            name = next((n for n, pattern in _HEAD_COLUMNS if pattern.match(text)), None)
            if name:
                named.append((name, float(box[0])))
        if not any(n == "qty" for n, _ in named) or not any(n == "description" for n, _ in named):
            continue
        current: dict[str, Any] | None = None
        for name, x in sorted(named, key=lambda pair: pair[1]):
            if current is None or name in current["columns"]:
                current = {"y": float(row.get("y") or 0.0), "columns": {}}
                tables.append(current)
            current["columns"][name] = x
    tables = [t for t in tables if {"qty", "description"} <= set(t["columns"])]
    for table in tables:
        xs = sorted(table["columns"].values())
        table["left"], table["right"] = xs[0] - _VALUE_SLACK, xs[-1] + _VALUE_REACH
    for table in tables:
        # A table ends where the next one to its right begins - beside it on the
        # sheet, whatever height that one's header sits at.
        beyond = [o["left"] for o in tables if o["left"] > table["left"] + _VALUE_REACH / 2]
        table["right"] = min([table["right"], *beyond])
    return tables


def _column_of(x: float, columns: dict[str, float]) -> str | None:
    """The column a value starting at x is under: the rightmost header it does not
    start well left of. The slack shrinks between close headers (QTY, DESCRIPTION)."""
    ordered = sorted(columns.items(), key=lambda pair: pair[1])
    best = None
    for index, (name, at) in enumerate(ordered):
        gap = at - ordered[index - 1][1] if index else _VALUE_SLACK * 2
        if at - min(_VALUE_SLACK, gap / 2) <= x:
            best = name
    return best


def _table_sets(rows: list[dict[str, Any]], page_number: int, page_size: dict[str, float]) -> list[dict[str, Any]]:
    """Every group in tables drawn under a QTY | DESCRIPTION header row."""
    tables = _table_headers(rows)
    ordered = sorted(rows, key=lambda r: float(r.get("y") or 0.0))
    sets: list[dict[str, Any]] = []
    for table in tables:
        # The block runs to the next header over the same column of the sheet.
        below = [t["y"] for t in tables if t["y"] > table["y"] + 2.0
                 and t["left"] < table["right"] and table["left"] < t["right"]]
        until = min(below, default=float("inf"))
        lines: list[dict[str, Any]] = []
        for row in ordered:
            y = float(row.get("y") or 0.0)
            if y <= table["y"] + 2.0 or y >= until:
                continue
            for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or []):
                x, text = float(box[0]), _text(cell)
                if not text or not table["left"] <= x < table["right"]:
                    continue
                column = _column_of(x, table["columns"])
                if column is None:
                    continue
                if not lines or y - lines[-1]["y"] > _ROW_TOLERANCE:
                    lines.append({"y": y, "cells": {}, "box": [round(float(v), 2) for v in box]})
                lines[-1]["cells"].setdefault(column, []).append(text)
        # The block has ended once its rows stop coming at their own pace.
        kept: list[dict[str, Any]] = []
        for line in lines:
            if len(kept) >= 3:
                gaps = sorted(b["y"] - a["y"] for a, b in zip(kept, kept[1:]))
                if line["y"] - kept[-1]["y"] > 3 * gaps[len(gaps) // 2]:
                    break
            kept.append(line)

        current: dict[str, Any] | None = None
        for line in kept:
            cells = line["cells"]
            group = " ".join(cells.get("group", []))
            values = {k: " ".join(v) for k, v in cells.items() if k not in ("group", "door")}
            started = _GROUP_ID.match(group) if group else None
            if started:
                current = {
                    "hardware_set": started.group(1).upper(), "set_id": started.group(1).upper(),
                    "specified": None, "source_page": page_number, "page_size": page_size,
                    "bbox": line["box"], "items": [], "flags": [],
                    "doors": [d.strip() for d in re.split(r"[,&]|\bAND\b", " ".join(cells.get("door", []))) if d.strip()],
                }
                sets.append(current)
            elif group and current is not None and values:
                # The group's name, written down its column beside its first items.
                current["specified"] = f"{current['specified'] or ''} {group}".strip()
            if current is None or not values:
                continue  # a note under a group, standing alone
            item = classify_item([values.get("qty", ""), values.get("description", ""),
                                  values.get("catalog", ""), values.get("finish", ""), values.get("mfg", "")])
            if _carries_information(item):
                current["items"].append(item)
    return sets


def _carries_information(item: dict[str, Any]) -> bool:
    """Whether a parsed row says anything an estimator could act on.

    A row that yields no part, no manufacturer and no unit is a wrapped fragment
    of the line above, not a hardware line of its own.
    """
    return any(item.get(field) for field in ("part", "manufacturer", "unit"))


def _reading_score(sets: list[dict[str, Any]]) -> int:
    """Items that name a manufacturer or a part: what a reading is worth to pricing."""
    return sum(
        1 for entry in sets for item in entry.get("items") or []
        if item.get("manufacturer") or item.get("part")
    )


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
        text_sets = _text_sets(page, page_number, page_size, shift)
    finally:
        doc.close()

    # Three layouts: sets side by side in columns, one table with its group
    # names written vertically, or a heading and quantity lines with no table.
    # Each reader can return something on another's page - the column reader
    # found "4: TAPE J-CHANNEL" in a wall-section note beside a matrix legend -
    # so the reading kept is the one whose items say the most.
    readings = [
        _column_sets(rows, _column_bands(rows), page_number, page_size),
        _matrix_sets(rows, words, page_number, page_size),
        text_sets,
        _table_sets(rows, page_number, page_size),
    ]
    sets = max(readings, key=_reading_score)
    if not _reading_score(sets):
        sets = next((reading for reading in readings if reading), [])
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
        # An item whose count is on one row and its part on the next: the cells it
        # has so far, until a row that states no count of its own completes it.
        opened: list[str] | None = None
        for _y, cells, boxes in sorted(per_column[band], key=lambda entry: entry[0]):
            joined = " | ".join(c for c in cells if c)
            header = SET_HEADER.search(joined)
            name = _text(header.group(2)) if header else None
            if header is None:
                header = SET_BARE.search(joined)
                name = None
            if header:
                # The heading's row may carry the first item's count and name -
                # `SET 05 - CLOSET DOOR | 1 1/2 PR. HINGES` - its part on the next row.
                name, *rest = (name or "").split(" | ")
                current = {
                    "hardware_set": header.group(1).upper(),
                    "set_id": header.group(1).upper(),
                    "specified": _text(name) or None,
                    "source_page": page_number,
                    "page_size": page_size,
                    "bbox": [round(float(v), 2) for v in boxes[0]] if boxes else None,
                    "items": [],
                    "flags": [],
                }
                sets.append(current)
                opened = None
                if rest and _is_item_row(rest):
                    first = classify_item(rest)
                    if _carries_information(first):
                        current["items"].append(first)
                        opened = rest if first["part"] is None and first["manufacturer"] is None else None
                continue
            if current is None or not _is_item_row(cells):
                opened = None
                continue
            states_count = bool(UNIT.search(joined) or QTY.match(joined))
            if opened is not None and not states_count:
                current["items"][-1] = classify_item(opened + cells)
                opened = None
                continue
            item = classify_item(cells)
            if not _carries_information(item):
                # A wrapped finish that spilled onto its own row ("626", "D / 626")
                # is a fragment of the line above, not a line. `raw_row` on the
                # real item still holds the text, so nothing is lost by not
                # inventing an item around it.
                continue
            current["items"].append(item)
            opened = cells if states_count and item["part"] is None and item["manufacturer"] is None else None
    return sets


# ── sets written as text: "HARDWARE SET NO. 3:" then "1 EA. MFR PART X FINISH" ──
# The prototype sheets and the 08 71 00 spec sections both write a set as a
# heading followed by quantity lines, with no table to band by column.

# "HARDWARE SET NO. 3:", "HARDWARE SET: 01", "HW GROUP 2", and the bare "GROUP #E1:" a
# prototype's bullet legend heads each group with.
TEXT_SET_HEADER = re.compile(
    r"^\s*(?:DOOR\s+)?(?:(?:HARDWARE|HDWR\.?|HW)\s*)?(?:SET|GROUP|GRP)" + _SET_NO + _SET_ID
    + r"\b\s*[:.\-–—]?\s*(.*)$",
    re.I,
)
TEXT_ITEM = re.compile(
    r"^\s*(\d+\s*-\s*\d/\d|\d+\s+\d/\d|\d+/\d|\d+(?:\.\d+)?)\s*"
    r"(EA|EACH|PR|PRS|PAIR|PAIRS|SET|SETS|LF|LOT)\b\.?\s*(.*)$",
    re.I,
)
NOT_USED = re.compile(r"^\s*(?:\(.*\)\s*)?NOT\s+USED\b", re.I)
_SUPPLIERS = (r"(G\.?C\.?|GENERAL\s+CONTRACTOR|OWNER|OTHERS|DOOR\s+MANUFACTURER"
              r"|(?:ALUM(?:INUM|\.)?\s+)?STOREFRONT\s+(?:SUPPLIER|CONTRACTOR|MANUFACTURER|VENDOR))")
BY_OTHERS_LINE = re.compile(
    r"\b(?:PROVIDED|FURNISHED|SUPPLIED)\b.*\bBY\s+(?:THE\s+)?" + _SUPPLIERS,
    re.I,
)
# A note under a group that hands the whole group to someone else:
# "TYPICAL HARDWARE (EQUAL OR BETTER) BY STOREFRONT SUPPLIER".
GROUP_BY_OTHERS = re.compile(r"\b(?:TYPICAL|ALL)\s+HARDWARE\b.*\bBY\s+(?:THE\s+)?" + _SUPPLIERS, re.I)
# A bullet legend's item: "CLOSER: HAGER MFG., MODEL #5200, ALM."
LABEL_ITEM = re.compile(r"^\s*[•·▪*]?\s*([A-Z][A-Z0-9 /&\-]{1,40}):\s*(\S.*)$")
_BULLET = re.compile(r"^\s*[•·▪]\s*$")
_LIST_NUMBER = re.compile(r"^\s*\d{1,2}\.\s*$")
# The one count such a line states: "(4) HINGES PER LEAF", "(1) PER LEAF".
COUNT_PER = re.compile(r"\((\d+)\)\s*(?:HINGES?\s+)?PER\s+(?:LEAF|DOOR|OPENING)\b", re.I)


def _supplier(text: str) -> str:
    """`ALUM. STOREFRONT CONTRACTOR` -> STOREFRONT; `G.C.` -> GC."""
    name = " ".join(text.upper().replace(".", "").split())
    return "STOREFRONT" if "STOREFRONT" in name else name


_HINGE = re.compile(r"\bHINGES?\b", re.I)
_CONTINUOUS = re.compile(r"\b(?:CONT(?:INUOUS|\.)?|GEARED|PIANO)\b", re.I)
_LONG = re.compile(r"(\d{2,3})\s*\"")


def assume_one_each(item: dict[str, Any]) -> None:
    """A legend that lists hardware with no counts means one of each per door, and
    the item says it was assumed. Not a butt hinge: three, four or a pair a leaf is
    a person's call - unless it is a continuous hinge, one door long (`700 83"`)."""
    if item.get("qty") is not None:
        return
    text = f"{item.get('description') or ''} {item.get('raw_row') or ''}"
    long_enough = any(int(n) >= 60 for n in _LONG.findall(text))
    if _HINGE.search(text) and not (_CONTINUOUS.search(text) or long_enough):
        if "hinge_count_unstated" not in item["flags"]:
            item["flags"].append("hinge_count_unstated")
        return
    item["qty"] = "1"
    item["flags"] = [f for f in item["flags"] if f != "qty_missing"] + ["qty_assumed_one"]


_DIMENSION = re.compile(r"""\d[\d'\-/."]*\s*[Xx]\s*\d[\d'\-/."]*""")
_KNOWN_BY_LENGTH = sorted(KNOWN_MANUFACTURERS, key=len, reverse=True)
_BHMA = re.compile(r"(?:US)?6[0-9]{2}", re.I)  # 626, 630, and the "US628" some sheets write


def _quantity(text: str) -> float | None:
    """'1-1/2' and '1 1/2' are one and a half, not one - the old reader's mistake."""
    text = text.strip().replace(" ", "-")
    try:
        if "-" in text and "/" in text:
            whole, frac = text.split("-", 1)
            num, den = frac.split("/")
            return float(whole) + float(num) / float(den)
        if "/" in text:
            num, den = text.split("/")
            return float(num) / float(den)
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


def classify_text_item(text: str) -> dict[str, Any]:
    """One quantity line: 'PEMKO 171A X 42" X DOUBLE NOTCH CUT ENDS X THRESHOLD'."""
    flat = " ".join(_PRIVATE_USE.sub(" ", text).replace(",", ", ").split())
    upper = flat.upper()
    manufacturer = None
    after = flat
    for name in _KNOWN_BY_LENGTH:
        match = re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", upper)
        if match:
            manufacturer = KNOWN_MANUFACTURERS[name]
            after = flat[match.end():]
            break
    words = [w.strip(",;()").lstrip("#") for w in after.split() if w.strip(",;()#")]

    def part_like(word: str) -> bool:
        if '"' in word or "'" in word or word.startswith(".") or FINISH.match(word) or _DIMENSION.fullmatch(word):
            return False
        if re.fullmatch(r"\d+\s*GA\.?", word, re.I) or _BHMA.fullmatch(word):
            return False  # a gauge, or a finish written "US628"
        return bool(_HAS_DIGIT.search(word) and (_HAS_LETTER.search(word) or len(word) >= 3))

    # The part follows the manufacturer; with no manufacturer there is nothing
    # to anchor it to, and a guessed part is worse than a flagged blank.
    part = next((w for w in words if part_like(w)), None) if manufacturer else None
    finishes = [w for w in words if w != part and (FINISH.match(w) and not w.isdigit() or _BHMA.fullmatch(w))]
    size = _DIMENSION.search(flat)
    item: dict[str, Any] = {
        "qty": None, "unit": None, "description": flat or None, "part": part,
        "finish": re.sub(r"^US(?=6\d\d$)", "", finishes[-1].upper()) if finishes else None,
        "manufacturer": manufacturer,
        "size": size.group(0) if size else None, "supplied_by": None, "raw_row": flat, "flags": [],
    }
    for field, flag in (("part", "part_missing"), ("manufacturer", "manufacturer_missing")):
        if item[field] is None:
            item["flags"].append(flag)
    return item


def _text_sets(page: Any, page_number: int, page_size: dict[str, float], shift: int) -> list[dict[str, Any]]:
    """Sets written as a heading and quantity lines, read in reading order."""
    lines: list[tuple[float, float, float, float, str]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"])
            if shift:
                text = pdfrows.shift_text(text, shift)
            if text.strip():
                lines.append((*line["bbox"], text))
    boxes = pdfrows.to_display_space(page, [(*line[:4], line[4]) for line in lines])

    # Sets laid out in columns side by side are read a column at a time, each top
    # to bottom: the page's own block order interleaves them, and a wrapped line
    # from one column would finish an item in the next.
    columns: list[float] = []
    for x in sorted(b[0] for b in boxes if TEXT_SET_HEADER.match(b[4])):
        if not columns or x - columns[-1] >= COLUMN_GAP:
            columns.append(x)
    if len(columns) > 1:
        width = min(b - a for a, b in zip(columns, columns[1:]))

        def column(b: tuple) -> int | None:
            if b[0] < columns[0] - 4.0 or b[0] >= columns[-1] + width:
                return None  # beside the legend: a schedule, a title block
            return max(i for i, left in enumerate(columns) if b[0] >= left - 4.0)

        boxes = sorted((b for b in boxes if column(b) is not None), key=lambda b: (column(b), b[1], b[0]))

    # A bullet or a list number is its own line, a little left of the text it marks
    # and a fraction of a point above or below it - so it is paired with that text
    # here, not by reading order: a bulleted line is an item, a numbered one a note.
    marked: dict[int, str] = {}
    for index, box in enumerate(boxes):
        kind = "item" if _BULLET.match(box[4]) else "note" if _LIST_NUMBER.match(box[4]) else None
        if kind is None:
            continue
        beside = [j for j, other in enumerate(boxes)
                  if j != index and abs(other[1] - box[1]) < 4.0 and 0 < other[0] - box[0] < 60
                  and not (_BULLET.match(other[4]) or _LIST_NUMBER.match(other[4]))]
        if beside:
            marked[min(beside, key=lambda j: boxes[j][0])] = kind

    sets: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    by_others: str | None = None
    last: tuple[dict[str, Any], tuple] | None = None
    for index, box in enumerate(boxes):
        x0, y0, x1, y1, text = box[:5]
        header = TEXT_SET_HEADER.match(text)
        if header:
            current = {
                "hardware_set": header.group(1).upper(),
                "set_id": header.group(1).upper(),
                "specified": _text(header.group(2)).strip(":() ") or None,
                "source_page": page_number,
                "page_size": page_size,
                "bbox": [round(float(v), 2) for v in (x0, y0, x1, y1)],
                "items": [],
                "flags": [],
            }
            sets.append(current)
            by_others, last = None, None
            if NOT_USED.search(header.group(2) or ""):
                current["flags"].append("not_used")
            continue
        if current is None or "not_used" in current["flags"]:
            continue
        if not current["items"] and NOT_USED.match(text):
            current["flags"].append("not_used")
            continue
        if _BULLET.match(text) or _LIST_NUMBER.match(text):
            continue  # a marker; the text beside it carries what it marks
        group_others = GROUP_BY_OTHERS.search(text)
        if group_others and not TEXT_ITEM.match(text):
            # The note covers the group: what is already read, and what follows.
            by_others = _supplier(group_others.group(1))
            for item in current["items"]:
                item["supplied_by"] = item["supplied_by"] or by_others
            last = None
            continue
        if marked.get(index) == "note":
            last = None  # a numbered note: the items above are complete
            continue
        item_match = TEXT_ITEM.match(text)
        beside_bullet = marked.get(index) == "item"
        label = LABEL_ITEM.match(text)
        others = BY_OTHERS_LINE.search(text)
        if others and not (item_match or label or beside_bullet):
            by_others = _supplier(others.group(1))
            last = None
            continue
        if item_match:
            qty, unit, rest = item_match.groups()
            item = classify_text_item(rest)
            count = _quantity(qty)
            unit = unit.upper().rstrip("S")
            if unit in ("PR", "PAIR") and count is not None:
                # Hinges are bought each: 1-1/2 pair is three hinges.
                item["qty"], item["unit"], item["qty_as_written"] = count * 2, "EA", f"{qty} {unit}"
            else:
                item["qty"], item["unit"] = count, "EA" if unit == "EACH" else unit
            if count is None:
                item["flags"].append("qty_missing")
        elif label or beside_bullet:
            # A bullet legend's line - `CLOSER: HAGER MFG., MODEL #5200, ALM.` - states
            # a count only as `(4) HINGES PER LEAF`; otherwise it is one a door.
            item = classify_text_item(text.lstrip(" •·▪*"))
            item["unit"], item["_count_unstated"] = "EA", True
            if others:
                item["supplied_by"] = _supplier(others.group(1))
        else:
            item = None
        if item is not None:
            if by_others and not item["supplied_by"]:
                item["supplied_by"] = "GC" if by_others in ("GC", "GENERAL CONTRACTOR") else by_others
            item["bbox"] = [round(float(v), 2) for v in (x0, y0, x1, y1)]
            current["items"].append(item)
            last = (item, box)
            continue
        # A wrapped line belongs to the item above it when it sits right under
        # it in the same column; anything else (a note, the title block) does not.
        if last is not None:
            item, prev = last
            height = max(prev[3] - prev[1], 6.0)
            # Right under it, or beside it on the same row (a set laid out in
            # columns: "1 EA. CLOSER" | "LCN 1460 ALUMINUM CLOSER").
            # Boxes of tightly set lines overlap: the next line may start a little
            # above the bottom of this one.
            below = -0.4 * height <= y0 - prev[3] <= 1.6 * height and abs(x0 - prev[0]) < 150
            beside = abs(y0 - prev[1]) < 0.6 * height and prev[0] < x0 < prev[2] + 400
            if below or beside:
                merged = classify_text_item(f"{item['raw_row']} {text}")
                for key in ("description", "raw_row", "size"):
                    item[key] = merged[key]
                for key in ("part", "finish", "manufacturer"):
                    item[key] = item[key] or merged[key]
                item["flags"] = [f for f in item["flags"]
                                 if not (f == "part_missing" and item["part"]) and not (f == "manufacturer_missing" and item["manufacturer"])]
                item["bbox"] = [round(min(item["bbox"][0], x0), 2), item["bbox"][1],
                                round(max(item["bbox"][2], x1), 2), round(float(y1), 2)]
                spilled = BY_OTHERS_LINE.search(text)
                if spilled and not item["supplied_by"]:
                    item["supplied_by"] = _supplier(spilled.group(1))
                last = (item, box)
            else:
                last = None
    for entry in sets:
        for item in entry["items"]:
            if item.pop("_count_unstated", False):
                count = COUNT_PER.search(item.get("raw_row") or "")
                if count:
                    item["qty"] = float(count.group(1))
                else:
                    assume_one_each(item)
    return [entry for entry in sets if entry["items"] or "not_used" in entry["flags"]]


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
