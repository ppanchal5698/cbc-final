"""Extract National Guard's lite-kit and louver price matrices (NR-8).

    python scripts/extract_lite_kits.py

Writes reference-library/adders/lite_kit_prices.json. Re-run it when NGP
publishes a new price list; the table is derived data and this is its source.

NR-8 named "the NGP, PEMKO/Markar and Rockwood sheets" as the source. Only
NGP has these grids: Pemko's single mention is prose, and Rockwood's are prep
notes ("Cut for Louver") and conditions ("Doors with Lites") - no prices.

Each page carries a width x height grid of list prices for one model group,
plus the option rules in prose above it. The grid is read by **right edge**:
the numbers are right-aligned in their columns, so a two-digit price starts
about a digit further right than a three-digit one and left-edge matching
silently shifts a column. Right edges land within a point of each other.

Nothing is smoothed. NGP really does print 95 at 10x10 and 78 at 12x12 while
their neighbours run 113-143; those are the catalog's numbers and reproducing
them faithfully is the whole job.
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]

import fitz  # noqa: E402

BOOK = ROOT / "pricebooks" / "national_guard_price_list.pdf"
COLUMN_TOLERANCE = 3.0  # points; right edges of one column vary by well under this
_INT = re.compile(r"^\d{1,4}$")
_RULE = re.compile(r"^[\u2022\-\*]\s*(.+)$")


def _numeric_words(page) -> list[tuple]:
    return [w for w in page.get_text("words") if _INT.match(w[4])]


def _find_header(words: list[tuple]) -> tuple[float, list[tuple[int, float]]] | None:
    """The WIDTH row: six or more ascending even integers sharing a baseline."""
    by_line: dict[float, list[tuple]] = {}
    for word in words:
        by_line.setdefault(round(word[1], 1), []).append(word)

    best = None
    for y, line in sorted(by_line.items()):
        line = sorted(line, key=lambda w: w[0])
        values = [int(w[4]) for w in line]
        if len(values) < 6:
            continue
        if values != sorted(values) or len(set(values)) != len(values):
            continue
        # A width header climbs steadily; a row of prices does not.
        steps = {values[i + 1] - values[i] for i in range(len(values) - 1)}
        if steps != {2} and steps != {2, 4}:
            continue
        if best is None or len(values) > len(best[1]):
            best = (y, [(int(w[4]), w[2]) for w in line])
    return best


def _grid(page) -> dict | None:
    words = _numeric_words(page)
    header = _find_header(words)
    if not header:
        return None
    header_y, columns = header
    widths = [w for w, _ in columns]
    edges = [x for _, x in columns]

    rows: dict[int, dict[int, int]] = {}
    by_line: dict[float, list[tuple]] = {}
    for word in words:
        if word[1] <= header_y:
            continue
        by_line.setdefault(round(word[1], 1), []).append(word)

    # Columns come from the price rows, not the header. A one-digit header ("6")
    # right-aligns half a point off a three-digit price ("113") - 89.5 against
    # 93.0 - so matching prices to header edges dropped the whole first column
    # while every other column passed. The prices agree with each other exactly.
    tally: dict[float, int] = {}
    for line in by_line.values():
        for word in line:
            if word[2] < edges[0] - COLUMN_TOLERANCE:
                continue  # the height label
            slot = next((e for e in tally if abs(e - word[2]) <= COLUMN_TOLERANCE), None)
            tally[slot if slot is not None else round(word[2], 1)] = (
                tally.get(slot, 0) + 1 if slot is not None else 1
            )
    ranked = sorted(tally.items(), key=lambda kv: -kv[1])[: len(widths)]
    if len(ranked) == len(widths):
        edges = sorted(e for e, _ in ranked)

    for y, line in sorted(by_line.items()):
        line = sorted(line, key=lambda w: w[0])
        # The leftmost number on the line is the height label; it sits left of
        # the first price column.
        label = next((w for w in line if w[2] < edges[0] - COLUMN_TOLERANCE), None)
        if label is None:
            continue
        height = int(label[4])
        cells: dict[int, int] = {}
        for word in line:
            if word is label:
                continue
            for width, edge in zip(widths, edges):
                if abs(word[2] - edge) <= COLUMN_TOLERANCE:
                    cells[width] = int(word[4])
                    break
        # A page can carry a second width header below the first - a continuation
        # table - and it reads as a data row whose "prices" are the widths
        # themselves: 8 under width 8, 12 under width 12. Three pages did that
        # and contributed 38 cells that were column labels wearing a price.
        looks_like_a_header = sum(
            1 for width, value in cells.items() if value == width
        ) >= max(3, len(cells) // 2)
        if cells and not looks_like_a_header and len(cells) >= len(widths) // 2:
            rows[height] = cells
    if not rows:
        return None
    return {"widths": widths, "prices": {str(h): rows[h] for h in sorted(rows)}}


def _context(page) -> dict:
    """Printed page and model group, taken by position.

    Every page in this book is laid out the same: the running date header, then
    the printed page number, then the contact line, then the models this grid
    prices. Pattern-matching the model line picked the date header instead;
    position is exact and the layout is the publisher's own template.

    The printed number matters as much as the models - it is what an estimator
    is told to turn to, and it does not equal the PDF page (NFR-3).
    """
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    printed = lines[1] if len(lines) > 1 and lines[1].isdigit() else None
    models = lines[3] if len(lines) > 3 else ""

    # Option rules sit between the model line and the grid, as bullets that wrap
    # across lines. Kept as written rather than parsed: "1.00 per perimeter
    # inch" and "5.00 per sq. ft. rounded up" are different formulas, and an
    # estimator reading them is safer than a parser guessing at them.
    # "HEIGHT" is the axis label and it sits *above* the bullets on some pages,
    # so stopping there lost every rule on the very page that carries the most.
    # The grid itself is the boundary: the first purely numeric line.
    rules, current = [], ""
    for line in lines[4:30]:
        if _INT.match(line):
            break
        if line.upper() in {"HEIGHT", "WIDTH"}:
            continue
        # A bullet arrives as U+2022 followed by a BEL the font uses for spacing.
        clean = line.lstrip("•-* \x07\t").strip()
        if line.startswith(("•", "-", "*")):
            if current:
                rules.append(current.strip())
            current = clean
        elif current:
            current += " " + clean
    if current:
        rules.append(current.strip())
    return {"printed_page": printed, "models": models, "rules": rules}


def main() -> int:
    doc = fitz.open(BOOK)
    out = []
    for index in range(doc.page_count):
        page = doc[index]
        text = page.get_text().upper()
        if "LITE KIT" not in text and "LOUVER" not in text:
            continue
        grid = _grid(page)
        if not grid:
            continue
        entry = {"pdf_page": index + 1, **_context(page), **grid}
        entry["cell_count"] = sum(len(v) for v in grid["prices"].values())
        out.append(entry)
    doc.close()

    target = ROOT / "reference-library" / "adders" / "lite_kit_prices.json"
    payload = {
        "description": "National Guard lite-kit and louver list prices, by width x height.",
        "source": f"pricebooks/{BOOK.name}",
        "extracted_by": "scripts/extract_lite_kits.py",
        "price_basis": "list",
        "note": (
            "List prices. Apply the NGP vendor multiplier to get cost, and add any "
            "option adders to the list figure first - see manual_adders.json."
        ),
        "sizing_rule": (
            "Odd-inch and fractional sizes take the next largest cell, as the page "
            "states. Outside a table's printed range the line is a vendor RFQ."
        ),
        "tables": out,
    }
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(
        f"{len(out)} tables, {sum(t['cell_count'] for t in out)} cells -> "
        f"{target.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
