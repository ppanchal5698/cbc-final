#!/usr/bin/env python3
"""pdf-tools MCP server - PDF text, tables, page images and search.

Every result carries source_page (1-indexed) so any extracted value can be traced
back to the drawing it came from (NFR-3, .claude/rules/auditability.md).

Architectural bid sets are CAD exports: a single sheet can carry >13,000 vector
line segments, so ruling-based table detection returns mostly noise. extract_tables
therefore clusters positioned words into rows instead. See
.claude/skills/extract-door-schedule/references/schedule_anatomy.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from _runtime import serve
from tools import TOOLS

from cbc.shared import pdfpages, pdfrows, pdftext

MAX_HITS = 200

# Budget guards.
#
# `extract_tables(page_range="all")` on a 28-page CAD set returns 1.5 million
# characters - roughly 385,000 tokens in a single tool call, a third of a context
# window spent before any estimating happens. A caller cannot know that in
# advance, so the tool has to bound it and say what it withheld.
#
# Nothing is dropped silently: the response names the pages it did not read and
# how to ask for them. Truncating a schedule without saying so would put missing
# openings into a quote.
MAX_TABLE_PAGES = 4
MAX_TEXT_PAGES = 4
MAX_ROWS_PER_PAGE = 300

# What a Division 8/10 take-off is looking for on an architectural set.
DEFAULT_SHEET_TERMS = [
    "door schedule",
    "door",
    "frame",
    "hardware",
    "opening",
    "finish schedule",
    "partition",
    "toilet",
    "restroom",
    "accessor",
    "frp",
    "wall type",
]

# Glyph repair and row clustering are in cbc_core/pdfrows.py: the catalog
# index reads price books with the same two, so a price and the drawing it
# was checked against cannot disagree about what a page says.


def _open(file_path: str) -> fitz.Document:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    return fitz.open(path)


def _parse_pages(doc: fitz.Document, spec: str | None) -> list[int]:
    """Return 0-indexed page numbers from a page-range spec such as 1-30, 14 or all."""
    if not spec or spec.strip().lower() == "all":
        return list(range(doc.page_count))
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            low, high = chunk.split("-", 1)
            out.extend(range(int(low) - 1, min(int(high), doc.page_count)))
        elif chunk:
            out.append(int(chunk) - 1)
    return [p for p in out if 0 <= p < doc.page_count]


def extract_text(
    file_path: str,
    pages: list[int] | str | None = None,
    max_pages: int = MAX_TEXT_PAGES,
) -> dict[str, Any]:
    """Text per page, with the glyph offset repaired when the fonts need it.

    `pages` takes a list of 1-indexed numbers or the same spec string
    extract_tables uses ("6", "1-30", "all"). It used to accept only a list and
    raised a TypeError on a string, which is the obvious thing to pass.
    """
    doc = _open(file_path)
    try:
        if isinstance(pages, str):
            wanted = _parse_pages(doc, pages)
        elif pages:
            wanted = [p - 1 for p in pages]
        else:
            wanted = list(range(doc.page_count))

        reading, deferred = wanted[:max_pages], wanted[max_pages:]
        shift = pdfrows.detect_shift(doc, file_path)
        out = []
        for index in reading:
            if not 0 <= index < doc.page_count:
                continue
            page = doc[index]
            text = pdftext.shifted_page_text(file_path, index, page, shift)
            ocr_used = False
            if not text.strip():
                text = pdfrows.ocr_page(page)
                ocr_used = True
            out.append(
                {
                    "source_page": index + 1,
                    "text": text,
                    "ocr_used": ocr_used,
                    "char_count": len(text),
                }
            )
        return {
            "file": file_path,
            "page_count": doc.page_count,
            "encoding_repaired": bool(shift),
            "encoding_shift": shift,
            "encoding_note": (
                f"This PDF embeds fonts with no usable ToUnicode map; glyph codes were "
                f"offset back by {shift} to recover readable text. Check any value that "
                f"looks wrong against the drawing."
                if shift
                else None
            ),
            "pages_read": [i + 1 for i in reading],
            "pages_deferred": [i + 1 for i in deferred],
            "note": (
                f"{len(deferred)} of the {len(wanted)} requested pages were not read, "
                f"to keep one call from spending the context the estimating needs. "
                f"Ask for them explicitly, e.g. pages="
                f"'{deferred[0] + 1}-{deferred[-1] + 1}'."
                if deferred
                else None
            ),
            "pages": out,
        }
    finally:
        doc.close()


def extract_tables(
    file_path: str,
    page_range: str | None = None,
    region: list[float] | None = None,
    max_pages: int = MAX_TABLE_PAGES,
    include_cell_boxes: bool = True,
) -> dict[str, Any]:
    """Rows of cells clustered from positioned words, bounded per call.

    Ask for the pages you need. Reading a whole bid set in one call costs more
    context than the estimating does - use search_pdf to find the schedule sheet
    first, then read that page.
    """
    doc = _open(file_path)
    try:
        shift = pdfrows.detect_shift(doc, file_path)
        requested = _parse_pages(doc, page_range)
        reading, deferred = requested[:max_pages], requested[max_pages:]
        out = []
        for index in reading:
            page = doc[index]
            rows = [dict(row) for row in pdftext.clustered_rows(file_path, index, page, region, shift)]
            # A dropped row is a missing opening in a quote, so a page that had to
            # be cut says so and says how much - never just a shorter list.
            total_rows = len(rows)
            truncated = total_rows > MAX_ROWS_PER_PAGE
            if truncated:
                rows = rows[:MAX_ROWS_PER_PAGE]
            if not include_cell_boxes:
                for row in rows:
                    row.pop("cell_boxes", None)
            if rows:
                out.append(
                    {
                        "source_page": index + 1,
                        "page_size": {
                            "width": round(page.rect.width, 2),
                            "height": round(page.rect.height, 2),
                        },
                        "row_count": len(rows),
                        "row_count_on_page": total_rows,
                        "rows_truncated": truncated,
                        "rows_note": (
                            f"Only the first {MAX_ROWS_PER_PAGE} of {total_rows} rows are "
                            f"here. Narrow with `region` to read the rest of this sheet."
                            if truncated
                            else None
                        ),
                        "rows": rows,
                    }
                )
        return {
            "file": file_path,
            "method": "word-position clustering",
            "encoding_repaired": bool(shift),
            "encoding_shift": shift,
            "pages_read": [i + 1 for i in reading],
            "pages_deferred": [i + 1 for i in deferred],
            "note": (
                f"{len(deferred)} of the {len(requested)} requested pages were not read, "
                f"to keep one call from spending the context the estimating needs. "
                f"Ask for them explicitly, e.g. page_range="
                f"'{deferred[0] + 1}-{deferred[-1] + 1}'."
                if deferred
                else None
            ),
            "pages": out,
        }
    finally:
        doc.close()


def find_sheets(file_path: str, queries: list[str] | None = None) -> dict[str, Any]:
    """A page map: which sheets mention which terms, and how often.

    The first question of every take-off is "which sheets matter?", and answering
    it with one `search_pdf` per term costs a turn and a page of context each -
    six searches on a one-page probe, for an answer that fits on a line.

    This returns counts rather than surrounding text: enough to choose the two or
    three sheets worth reading properly, and not enough to be tempted to read the
    set from here.
    """
    terms = [q for q in (queries or DEFAULT_SHEET_TERMS) if q and q.strip()]
    doc = _open(file_path)
    try:
        shift = pdfrows.detect_shift(doc, file_path)
        pages: list[dict[str, Any]] = []
        totals: dict[str, int] = {t: 0 for t in terms}

        for index in range(doc.page_count):
            text = pdftext.shifted_page_text(file_path, index, doc[index], shift).lower()
            hits = {t: text.count(t.lower()) for t in terms}
            hits = {t: n for t, n in hits.items() if n}
            if not hits:
                continue
            for term, count in hits.items():
                totals[term] += count
            pages.append(
                {
                    "source_page": index + 1,
                    "terms": dict(sorted(hits.items(), key=lambda kv: -kv[1])),
                    "score": sum(hits.values()),
                }
            )

        pages.sort(key=lambda p: -p["score"])
        return {
            "file": file_path,
            "page_count": doc.page_count,
            "encoding_repaired": bool(shift),
            "queried": terms,
            "not_found": sorted(t for t, n in totals.items() if not n),
            "pages": pages,
            "note": (
                "Ranked by how many of the queried terms each sheet carries. Read the "
                "top sheets with extract_tables; do not read them all."
            ),
        }
    finally:
        doc.close()


def get_page_size(file_path: str, page_number: int) -> dict[str, Any]:
    """Page dimensions in PDF points - the frame every bbox is measured against.

    Shared with the API (cbc_core/pdfpages.py), because a bbox recorded here is
    scaled against this frame on the review screen: two implementations of it
    would put the highlight in the wrong place.
    """
    return pdfpages.page_size(file_path, page_number)


def get_page_image(
    file_path: str,
    page_number: int,
    dpi: int = 200,
    out_dir: str | None = None,
    region: list[float] | None = None,
) -> dict[str, Any]:
    return pdfpages.page_image(file_path, page_number, dpi, out_dir, region)


def search_pdf(
    file_path: str, query: str, context_chars: int = 160, max_hits: int = 40
) -> dict[str, Any]:
    """Where a phrase appears, with enough context to tell hits apart.

    This is the cheap way to find the sheet you want before reading it. The
    context window is deliberately small - a search that returns the page is
    doing its job; extract_tables reads it.
    """
    try:
        capped_hits = max(1, min(int(max_hits), MAX_HITS))
    except (TypeError, ValueError):
        capped_hits = 40
    doc = _open(file_path)
    try:
        needle = query.lower()
        half = max(context_chars // 2, 40)
        # Without the repair a search for "DOOR SCHEDULE" finds nothing on a set
        # whose glyph codes are offset, and reports it as absent rather than as
        # unreadable - the worst possible answer.
        shift = pdfrows.detect_shift(doc, file_path)
        hits: list[dict[str, Any]] = []
        for index in range(doc.page_count):
            text = pdftext.shifted_page_text(file_path, index, doc[index], shift)
            lowered = text.lower()
            start = lowered.find(needle)
            while start != -1 and len(hits) < capped_hits:
                left = max(0, start - half)
                hits.append(
                    {
                        "source_page": index + 1,
                        "offset": start,
                        "context": text[left : start + len(query) + half],
                    }
                )
                start = lowered.find(needle, start + 1)
            if len(hits) >= capped_hits:
                break
        return {"file": file_path, "query": query, "hit_count": len(hits), "hits": hits}
    finally:
        doc.close()


HANDLERS = {
    "find_sheets": find_sheets,
    "extract_text": extract_text,
    "extract_tables": extract_tables,
    "get_page_image": get_page_image,
    "get_page_size": get_page_size,
    "search_pdf": search_pdf,
}


if __name__ == "__main__":
    serve("pdf-tools", TOOLS, HANDLERS)
