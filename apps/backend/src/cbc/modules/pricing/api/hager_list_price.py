"""Resolve NGP list prices from Hager Price Book #18 for Path 2 pricing.

Architect schedules often cite Pemko or Zero numbers (275A, 39A, 188S). The Hager
book lists NGP codes with comparison-number columns instead. Agents running from a
sandbox cwd used to fail opening ``data/pricebooks/...``; even with path resolution
fixed, text search for ``275A`` returns nothing. This module maps common architect
parts to NGP rows and reads MIL list prices from the PDF.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

import fitz

from cbc.shared import pdfpages, pdftext, pdfrows

log = logging.getLogger("cbc.pricing.hager")

HAGER_BOOK = "data/pricebooks/hager_price_book_18.pdf"
THRESHOLD_PAGES = range(515, 536)  # 0-indexed pages in the threshold section

_PRICE = re.compile(r"\$(\d+\.\d+)")
_NGP = re.compile(r"\b(\d{3}S)\b")
_WIDTH_QUOTED = re.compile(r'(\d+)\s*"')
_WIDTH_INCHES = re.compile(r"(\d+)\s*in(?:ch(?:es)?)?\b", re.I)
_WIDTH_HYPHEN = re.compile(r"-(\d{2})(?:\D|$)")
_SKIP_TOKENS = frozenset({"ZERO", "PEMKO", "NGP", "HAGER", "NATIONAL", "GUARD"})


def parse_width_inches(*values: Any) -> int | None:
    """Door width from ``42"``, ``42 inches``, or a hyphenated SKU such as ``275A-42``."""
    for raw in values:
        text = str(raw or "")
        match = _WIDTH_QUOTED.search(text) or _WIDTH_INCHES.search(text)
        if match:
            return int(match.group(1))
    for raw in values:
        match = _WIDTH_HYPHEN.search(str(raw or ""))
        if not match:
            continue
        width = int(match.group(1))
        if 24 <= width <= 48:
            return width
    return None


def ngp_for_architect_item(
    item_type: str,
    part_number: str,
    *,
    width_in: int | None = None,
) -> tuple[str, str] | None:
    """Map architect threshold / weatherstrip lines to an NGP stock code."""
    kind = str(item_type or "").strip().lower()
    tokens = [t for t in re.split(r"[^A-Z0-9]+", str(part_number or "").upper()) if t]
    token = next((t for t in tokens if t not in _SKIP_TOKENS), "")
    if not token and tokens:
        token = tokens[-1]

    if "threshold" in kind or token.startswith("275"):
        return (
            "431S",
            "Pemko 275A → NGP 431S commercial half-saddle (verify profile/finish)",
        )
    if any(word in kind for word in ("door_shoe", "door_sweep", "sweep", "shoe")) or token.startswith("39"):
        if width_in is not None and width_in >= 42:
            return ("801S", f"Zero 39A → NGP 801S brush sweep {width_in}\"")
        return ("750S", f"Zero 39A → NGP 750S heavy-duty sweep {width_in or '?'}\"")
    if any(word in kind for word in ("door_seal", "seal", "weatherstrip")) or token.startswith("188"):
        return ("785S", "Zero 188S → NGP 785S jamb weatherstrip (Pemko 188 column)")
    return None


@lru_cache(maxsize=1)
def _book() -> tuple[str, fitz.Document, int] | None:
    """The Hager book, or None when it is not on disk.

    This backfill is an *enhancement*: it fills a cost for lines that have none,
    and skips any line that already carries one. So a missing book means "no
    backfill", not "no quote". It used to raise `FileNotFoundError` out of
    `sync_results`, which the worker reports as `sync_failed` - a job whose Claude
    pass had already succeeded and written valid line items was failed three
    times over a PDF nobody had shipped, at $1.78 an attempt.
    """
    try:
        path = pdfpages.resolve_pdf_path(HAGER_BOOK)
    except FileNotFoundError:
        log.warning(
            "%s is not on disk - skipping the NGP list-price backfill. Lines that "
            "would have been priced from it stay MANUAL.",
            HAGER_BOOK,
        )
        return None
    doc = fitz.open(path)
    shift = pdfrows.detect_shift(doc, str(path))
    return str(path), doc, shift


def book_available() -> bool:
    """Whether the backfill can run at all, for callers that want to say so."""
    return _book() is not None


def lookup_ngp_list_price(
    ngp_code: str,
    *,
    width_in: int | None = None,
) -> dict[str, Any] | None:
    """Return MIL list price for an NGP code, optionally width-aware."""
    code = str(ngp_code or "").strip().upper()
    if not code:
        return None

    book = _book()
    if book is None:
        return None
    file_path, doc, shift = book
    if width_in is not None:
        hit = _list_price_with_width(doc, shift, file_path, code, width_in)
        if hit:
            return hit

    for page_index in THRESHOLD_PAGES:
        text = pdftext.shifted_page_text(file_path, page_index, doc[page_index], shift)
        hit = _list_price_near_code(text, code)
        if hit:
            price, _offset = hit
            return {
                "ngp_code": code,
                "list_price": price,
                "source_page": page_index + 1,
                "file_path": HAGER_BOOK,
                "width_in": width_in,
            }
    return None


def _list_price_near_code(text: str, code: str) -> tuple[float, int] | None:
    idx = text.find(code)
    if idx < 0:
        return None
    window = text[idx : idx + 500]
    mil = window.find("MIL")
    if mil < 0:
        return None
    prices = _PRICE.findall(window[mil : mil + 120])
    if not prices:
        return None
    return float(prices[0]), idx


def _list_price_with_width(
    doc: fitz.Document,
    shift: int,
    file_path: str,
    code: str,
    width_in: int,
) -> dict[str, Any] | None:
    """Scan table rows after ``code`` for a width column, then read the MIL price."""
    width_text = str(width_in)
    for page_index in THRESHOLD_PAGES:
        page = doc[page_index]
        rows = pdfrows.rows_from_words(page, shift=shift)
        for index, row in enumerate(rows):
            line = " | ".join(row["cells"])
            if code not in line:
                continue
            window = rows[index : index + 8]
            for follow in window:
                cells = " | ".join(follow["cells"])
                if width_text not in cells:
                    continue
                if "MIL" not in cells:
                    continue
                prices = _PRICE.findall(cells)
                if prices:
                    return {
                        "ngp_code": code,
                        "list_price": float(prices[0]),
                        "source_page": page_index + 1,
                        "file_path": HAGER_BOOK,
                        "width_in": width_in,
                    }
    return None
