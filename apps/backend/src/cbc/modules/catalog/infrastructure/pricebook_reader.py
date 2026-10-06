"""Read a vendor price book's tables into priced rows, by geometry, with no model.

A Hager-style book prints each table under a bold header row (Description, Size,
Finish, List, Box/Case Qty.). The part number is bold in the Description column,
its description follows in light type, and every finish sits on one line with
its list price. Sizes are printed centred beside their block of finish rows, and
the first row of each block carries the box and case quantity - so a block is
the run of rows from one quantity row to the next.

Every row comes back with the page it was read from, the printed page number,
the footer's effective date and the box around the price, which is what an
estimator needs to find it again (NFR-3). A page with no such table yields
nothing; `read_book` says which pages had a header but produced no rows, so
those can go to the `read_price_row` question instead of being lost silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

BOLD = 16
_PRICE = re.compile(r"^\$?(\d{1,3}(?:,\d{3})*|\d+)\.\d{2}$")
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_PART_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9\-/.]*$")
_HEADER_WORDS = {"Description", "Function", "Materials", "Size", "Finish", "List", "Box", "Case", "Qty.", "Qty"}
FOOTER_Y = 715.0  # below this on a 783pt page: date, page number, web address


@dataclass
class Span:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    bold: bool
    size: float


@dataclass
class Header:
    y: float
    x_lo: float
    x_hi: float
    desc_x: float
    size_x: float | None
    finish_x: float
    list_x: float
    qty_x: float | None
    title: str = ""
    y_end: float = FOOTER_Y


@dataclass
class Row:
    model: str
    description: str
    size: str | None
    finish: str | None
    list_price: float
    bbox: list[float]
    table: str = ""


@dataclass
class PageResult:
    page: int
    printed_page: str | None
    effective: str | None
    title: str
    rows: list[Row] = field(default_factory=list)
    headers: int = 0


_QUOTES = str.maketrans({"’": "'", "‘": "'", "”": '"', "“": '"', "″": '"', "�": '"'})


def _spans(page: fitz.Page) -> list[Span]:
    """Every text span once. Some pages overprint their text layer, which read
    as every table twice."""
    out, seen = [], set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                text = " ".join(s["text"].translate(_QUOTES).split())
                x0, y0, x1, y1 = s["bbox"]
                key = (round(x0), round(y0), text)
                if text and key not in seen:
                    seen.add(key)
                    out.append(Span(x0, y0, x1, y1, text, bool(s["flags"] & BOLD), s["size"]))
    return out


def _same_line(a: float, b: float, tol: float = 2.5) -> bool:
    return abs(a - b) <= tol


def _headers(spans: list[Span], width: float) -> list[Header]:
    finishes = [s for s in spans if s.bold and s.text == "Finish"]
    found: list[Header] = []
    for fin in finishes:
        # Side-by-side tables share a header line; this one starts after the
        # List column of the table to its left.
        left = max((s.x0 for s in spans if s.bold and s.text == "List" and _same_line(s.y0, fin.y0)
                    and s.x0 < fin.x0), default=-1.0)
        left = max((s.x0 for s in spans if s.bold and s.text.startswith("Qty") and _same_line(s.y0, fin.y0)
                    and left < s.x0 < fin.x0), default=left)
        row = [s for s in spans if s.bold and _same_line(s.y0, fin.y0) and s.text in _HEADER_WORDS
               and s.x0 > left]
        lists = sorted((s for s in row if s.text == "List" and s.x0 > fin.x0), key=lambda s: s.x0)
        descs = sorted((s for s in row if s.text == "Description" and s.x0 < fin.x0), key=lambda s: -s.x0)
        if not lists:
            continue
        lst = lists[0]
        sizes = [s for s in row if s.text == "Size" and s.x0 < fin.x0]
        qtys = sorted((s for s in row if s.text.startswith("Qty") and s.x0 > lst.x0), key=lambda s: s.x0)
        # A lock table heads its columns "Function Finish List" with no
        # Description, and prints the part number left of the first heading.
        desc_x = descs[0].x0 if descs else min(s.x0 for s in row) - 30
        found.append(Header(
            y=fin.y0, x_lo=desc_x - 12, x_hi=width, desc_x=desc_x,
            size_x=sizes[-1].x0 if sizes else None, finish_x=fin.x0, list_x=lst.x0,
            qty_x=qtys[0].x0 if qtys else None,
        ))
    found.sort(key=lambda h: (h.y, h.x_lo))
    # Side-by-side tables share a header line: each one ends where the next begins.
    for h in found:
        right = [o.x_lo for o in found if _same_line(o.y, h.y) and o.x_lo > h.x_lo]
        if right:
            h.x_hi = min(right)
    for h in found:
        below = [o.y for o in found if o.y > h.y + 5 and o.x_lo < h.x_hi and o.x_hi > h.x_lo]
        if below:
            h.y_end = min(below) - 12
    for h in found:
        above = [s for s in spans if s.bold and h.y - 16 < s.y0 < h.y - 3 and h.x_lo <= s.x0 < h.finish_x
                 and s.text not in _HEADER_WORDS]
        h.title = " ".join(s.text for s in sorted(above, key=lambda s: s.x0))
    return found


def _is_part(span: Span) -> bool:
    """A bold part number: "BB1279", "2-300-0036", "6017 Series" - not "5100 Series
    Lever Lockset" or a section title."""
    tokens = [t for t in span.text.split() if t != "Series"]
    return (
        span.bold
        and span.text not in _HEADER_WORDS
        and 0 < len(tokens) <= 3
        and _PART_TOKEN.match(tokens[0]) is not None
        and any(c.isdigit() for c in tokens[0])
        and not any(c.islower() for c in " ".join(tokens))
    )


_DIMENSION = re.compile(r'\d[\d\-/.]*"?\s*x\s*\d[\d\-/.]*"?')


def _price(text: str) -> float | None:
    m = _PRICE.match(text.strip())
    return float(text.strip().lstrip("$").replace(",", "")) if m else None


def _blocks(
    prices: list[tuple[Span, float]], finishes: list[Span], qty_rows: list[float], parts: list[Span]
) -> list[list[tuple[Span, float, Span | None]]]:
    """Split a table's price rows into the blocks one part-and-size prices.

    A block starts at a row carrying a box/case quantity. A table without that
    column prints its part on the block's first line, and lists each finish once
    per block, so there a part on the line or a repeated finish starts one.
    """
    blocks: list[list[tuple[Span, float, Span | None]]] = []
    seen: set[str] = set()
    for span, price in sorted(prices, key=lambda sp: sp[0].y0):
        finish = next((f for f in finishes if _same_line(f.y0, span.y0)), None)
        name = finish.text if finish else ""
        if qty_rows:
            starts = any(_same_line(span.y0, q) for q in qty_rows)
        else:
            starts = name in seen or any(_same_line(span.y0, p.y0) for p in parts)
        if starts or not blocks:
            blocks.append([])
            seen = set()
        blocks[-1].append((span, price, finish))
        seen.add(name)
    return blocks


def _table_rows(spans: list[Span], h: Header) -> list[Row]:
    inside = [s for s in spans if h.x_lo <= s.x0 < h.x_hi and h.y + 3 < s.y0 < h.y_end]
    size_lo = (h.size_x - 32) if h.size_x is not None else None
    finish_lo = h.finish_x - 22
    desc_hi = size_lo if size_lo is not None else finish_lo
    list_hi = (h.qty_x - 6) if h.qty_x is not None else h.list_x + 45

    parts = sorted((s for s in inside if s.x0 < desc_hi and _is_part(s)), key=lambda s: s.y0)
    prices = [(s, p) for s in inside if h.list_x - 10 <= s.x0 < list_hi and (p := _price(s.text)) is not None]
    finishes = [s for s in inside if finish_lo <= s.x0 < h.list_x - 10]
    sizes = [s for s in inside if size_lo is not None and size_lo <= s.x0 < finish_lo and not s.text.startswith("(")]
    qty_rows = [s.y0 for s in inside if h.qty_x is not None and s.x0 >= h.qty_x - 6]
    desc = sorted((s for s in inside if s.x0 < desc_hi and not _is_part(s)), key=lambda s: s.y0)

    def text_between(lo: float, hi: float) -> str:
        return " ".join(s.text for s in desc if lo <= s.y0 <= hi)

    rows: list[Row] = []
    first_lo: dict[int, float] = {}
    last_description: dict[int, str] = {}
    blocks = _blocks(prices, finishes, qty_rows, parts)
    for index, block in enumerate(blocks):
        lo, hi = block[0][0].y0 - 8, block[-1][0].y0 + 8
        # This block's own text runs on below its last row - a one-row part
        # prints its description underneath - until the next block or part.
        next_lo = blocks[index + 1][0][0].y0 - 8 if index + 1 < len(blocks) else h.y_end
        next_part = min((p.y0 for p in parts if p.y0 > hi), default=h.y_end)
        span_end = min(next_lo, next_part if next_part > hi else h.y_end, h.y_end)
        # The parts printed beside this block. A lock table lists several
        # functions beside one price block, all at that price: when the block
        # starts with its own part, every part down to the next block shares it.
        # A block with none takes the nearest part above - the part a run of
        # size blocks continues, or one printed over its table.
        own = [p for p in parts if lo <= p.y0 <= hi]
        if own:
            mine = [p for p in parts if lo <= p.y0 < max(hi, next_lo)]
        else:
            above = next((p for p in reversed(parts) if p.y0 < lo), None)
            mine = [above] if above else []
        size = next((z.text for z in sizes if lo <= z.y0 <= hi), None)
        for n, part in enumerate(mine):
            key = id(part)
            first_lo.setdefault(key, lo)
            if len(mine) > 1:
                stop = mine[n + 1].y0 if n + 1 < len(mine) else max(hi, next_lo)
                local = text_between(part.y0 + 1, stop - 0.1)
                intro = ""
            else:
                # Text beside the block is this variant's own (a size, a
                # function); text between the part and its first block is the
                # part's description.
                local = text_between(lo, max(hi, span_end - 0.1))
                intro = text_between(part.y0 + 1, first_lo[key] - 0.1) if part.y0 < first_lo[key] else ""
            description = " ".join(t for t in (intro, local) if t) or last_description.get(key, "")
            last_description[key] = description
            part_size = size
            if part_size is None and (m := _DIMENSION.search(local)):
                part_size = m.group(0)
            for span, price, finish in block:
                x0 = finish.x0 if finish else span.x0
                rows.append(Row(
                    model=part.text.split()[0],
                    description=description,
                    size=part_size,
                    finish=finish.text if finish else None,
                    list_price=price,
                    bbox=[round(x0, 1), round(span.y0, 1), round(span.x1, 1), round(span.y1, 1)],
                    table=h.title,
                ))
    return rows


def read_page(page: fitz.Page, number: int) -> PageResult:
    spans = _spans(page)
    footer = [s for s in spans if s.y0 >= FOOTER_Y]
    effective = None
    for s in footer:
        if m := _DATE.match(s.text):
            effective = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    printed = next((s.text for s in footer if s.text.isdigit()), None)
    title = " ".join(s.text for s in spans if s.bold and s.size >= 13 and s.y0 < 60)
    result = PageResult(number, printed, effective, title)
    headers = _headers(spans, page.rect.width)
    result.headers = len(headers)
    for h in headers:
        result.rows.extend(_table_rows(spans, h))
    return result


def read_book(path: str | Path, pages: list[int] | None = None) -> dict[str, Any]:
    """Every priced row in the book, plus the pages that had a table but gave none."""
    with fitz.open(str(path)) as doc:
        numbers = pages or list(range(1, doc.page_count + 1))
        results = [read_page(doc[n - 1], n) for n in numbers]
    return {
        "pages": results,
        "rows": sum(len(r.rows) for r in results),
        "unread_pages": [r.page for r in results if r.headers and not r.rows],
    }


if __name__ == "__main__":  # python -m ... <book.pdf> [page ...]
    import sys

    book = read_book(sys.argv[1], [int(p) for p in sys.argv[2:]] or None)
    for result in book["pages"]:
        for row in result.rows[:400]:
            print(result.page, result.printed_page, result.effective, "|", row.table, "|", row.model,
                  row.size, row.finish, row.list_price, "|", row.description[:50])
    print("rows", book["rows"], "unread pages", book["unread_pages"][:50], len(book["unread_pages"]))
