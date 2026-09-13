#!/usr/bin/env python3
"""catalog MCP server - navigate the vendor price books, do not pre-digest them.

This used to serve product rows out of a SQLite FTS index built by extracting
every line of every catalog. Vendor catalogs are too irregular for that: 37.8% of
the codes it produced contained no letter at all, 183 dates were recorded as part
numbers, one vendor's sheet yielded nothing while reporting success, and a
pricing pass reading those rows had no way to tell a misread number from a real
one.

It now reads a page index: a two-line description of every page of every catalog,
in MongoDB, with the part families on it and whether it carries prices. The tools
answer "which page" - and the price comes off that page, read with pdf-tools
during the run that quotes it.

Nothing here returns a price. That is the design, not an omission.

READ-ONLY, and enforced rather than promised: the connection uses
MONGODB_READONLY_URI and refuses to fall back to the writable string.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from _runtime import serve
from tools import TOOLS

from cbc.modules.catalog.api.pageindex import basis as price_basis_of
from cbc.modules.catalog.api.pageindex import models as page_models
from cbc.modules.catalog.api.pageindex import query as page_query
from cbc.modules.catalog.api.pageindex import reader

from cbc.modules.ops.api.freshness import load_sync
from cbc.modules.pricing.api import reference_library as reflib  # noqa: E402

MAX_LIMIT = 25


def _clamp(limit: Any, default: int = 8) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _unavailable(exc: Exception) -> dict[str, Any]:
    return {
        "error": str(exc),
        "note": (
            "The page index is not readable from this run. Price these lines "
            "manually rather than guessing - do not substitute a similar part."
        ),
    }


# ── navigation: which page, never what price ───────────────────────────────


def list_catalogs(vendor: str | None = None) -> dict[str, Any]:
    """Indexed catalogs, with age and whether their prices are list or net."""
    from datetime import date

    try:
        rows = reader.list_catalogs(vendor)
    except Exception as exc:
        return _unavailable(exc)

    catalogs = []
    stale_days = load_sync().catalog_stale_days
    for row in rows:
        effective = row.get("effectiveDate")
        age = None
        if effective:
            try:
                age = (date.today() - date.fromisoformat(effective)).days
            except (ValueError, TypeError):
                age = None
        catalogs.append(
            {
                "catalog_id": row["_id"],
                "vendor": row.get("vendor"),
                "file": row.get("fileName"),
                "kind": row.get("kind"),
                "price_basis": row.get("priceBasis"),
                "pages": row.get("pageCount", 0),
                "effective_date": effective,
                "age_days": age,
                "stale": age is not None and age > stale_days,
                "undated": effective is None,
            }
        )
    return {
        "count": len(catalogs),
        "pages": sum(c["pages"] for c in catalogs),
        "stale": sum(1 for c in catalogs if c["stale"]),
        "catalogs": catalogs,
        "note": (
            "NFR-10 is open - no named owner or refresh cadence for these sheets; "
            "age is the only staleness signal."
        ),
    }


def _document(catalog_id: str):
    row = reader.get_catalog(catalog_id)
    return page_models.PageIndexDocument.from_mongo(row) if row else None


def get_catalog_overview(catalog_id: str) -> dict[str, Any]:
    """What this catalog is, before going looking for a page in it."""
    try:
        document = _document(catalog_id)
    except Exception as exc:
        return _unavailable(exc)
    if document is None:
        return {"found": False, "catalog_id": catalog_id, "note": "no such catalog"}
    overview = document.overview
    return {
        "found": True,
        "catalog_id": document.catalog_id,
        "vendor": document.vendor,
        "file": document.file_name,
        "kind": document.kind,
        "price_basis": document.price_basis,
        "price_basis_note": price_basis_of.describe(document.price_basis),
        "effective_date": document.effective_date,
        "page_count": document.page_count,
        "summary": overview.summary,
        "product_lines": overview.product_lines,
        "how_prices_are_shown": overview.how_prices_are_shown,
        "gotchas": overview.gotchas,
        "how_to_find_a_part": overview.how_to_find_a_part,
    }


def _rank_uncached(query: str, vendor: str | None, limit: int) -> dict[str, Any]:
    documents = [
        page_models.PageIndexDocument.from_mongo(row)
        for row in reader.all_catalogs(vendor)
    ]
    return page_query.rank_pages(documents, query, limit=limit)


@lru_cache(maxsize=256)
def _rank_cached(
    query_norm: str, vendor_key: str, limit: int, watermark: str
) -> dict[str, Any]:
    vendor = vendor_key or None
    return _rank_uncached(query_norm, vendor, limit)


def clear_find_pages_cache() -> None:
    _rank_cached.cache_clear()


def find_pages(query: str, vendor: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Pages worth opening. Read the price off the page, not out of this."""
    if not str(query or "").strip():
        return {"error": "query is required", "count": 0, "pages": []}
    try:
        headers = reader.list_catalogs(vendor)
        if not vendor and len(headers) > 10:
            return {
                "query": query,
                "count": 0,
                "pages": [],
                "note": (
                    "Too many catalogs to search without a vendor filter. "
                    "Pass vendor= to narrow the search."
                ),
            }
        watermark = page_query.headers_watermark(headers)
        ranked = _rank_cached(
            str(query).strip().lower(),
            str(vendor or "").strip().lower(),
            _clamp(limit),
            watermark,
        )
        return copy.deepcopy(ranked)
    except Exception as exc:
        return _unavailable(exc)


def get_page(catalog_id: str, pdf_page: int) -> dict[str, Any]:
    """One page's entry, for confirming a citation."""
    try:
        document = _document(catalog_id)
    except Exception as exc:
        return _unavailable(exc)
    if document is None:
        return {"found": False, "note": "no such catalog"}
    for page in document.pages:
        if page.pdf_page == int(pdf_page):
            return {
                "found": True,
                "catalog_id": document.catalog_id,
                "file": document.file_name,
                "file_path": f"{page_query.PRICEBOOK_DIR}/{document.file_name}",
                "pdf_page": page.pdf_page,
                "printed_page": page.printed_page,
                "locator": page.locator(),
                "title": page.title,
                "description": page.description,
                "code_prefixes": page.code_prefixes,
                "keywords": page.keywords,
                "has_prices": page.has_prices,
                "kind": page.kind,
                "confidence": page.confidence,
                "price_basis": document.price_basis,
                "effective_date": document.effective_date,
            }
    return {"found": False, "note": f"{catalog_id} has no page {pdf_page}"}


# ── curated reference data (Mongo via reference_library; seed JSON fallback) ─


def get_special_net(vendor: str, part_number: str) -> dict[str, Any] | None:
    """Fixed net price from the multiplier sheet, when one exists for this part."""
    return reflib.get_special_net(vendor, part_number)


def is_stock_item(vendor: str, part_number: str) -> dict[str, Any]:
    """NR-6 top-10 stock list lookup."""
    return reflib.is_stock_part(vendor, part_number)


def get_multiplier(vendor: str, category: str | None = None) -> dict[str, Any]:
    """From the tier sheet purchasing maintains. Never inferred from a PDF."""
    return reflib.get_vendor_tier(vendor, category)


HANDLERS = {
    "list_catalogs": list_catalogs,
    "get_catalog_overview": get_catalog_overview,
    "find_pages": find_pages,
    "get_page": get_page,
    "get_multiplier": get_multiplier,
    "get_special_net": get_special_net,
    "is_stock_item": is_stock_item,
}

# Guardrail: this server reads. It holds a credential that cannot write, and it
# exposes no tool that claims to.
_FORBIDDEN = ("write", "update", "insert", "upsert", "delete", "create", "set_")
assert not [t for t in TOOLS if any(word in t["name"].lower() for word in _FORBIDDEN)], (
    "catalog must expose no write tools"
)
assert set(HANDLERS) == {t["name"] for t in TOOLS}, "every tool needs a handler"


def _demo() -> None:
    """Runnable check against the real index."""
    catalogs = list_catalogs()
    if "error" in catalogs:
        print(f"catalog demo SKIPPED - {catalogs['error'][:80]}")
        return

    assert catalogs["count"] > 0, "no catalogs indexed - run `python -m cbc.modules.catalog.api.pageindex.build --all`"

    hit = find_pages("3400 lock", vendor="hager", limit=3)
    assert hit["count"] >= 1, hit
    top = hit["pages"][0]
    # The pair NFR-3 needs: what pdf-tools takes, and what the page prints.
    assert top["pdf_page"] >= 1 and top["locator"], top
    assert top["why"], "a hit must say why it matched"
    # And nothing here quotes a price.
    assert "price" not in top or top.get("price") is None

    miss = find_pages("definitely-not-a-real-part-xyz")
    assert miss["count"] == 0 and "MANUAL cut-off" in miss["note"]

    assert get_multiplier("acme")["multiplier"] is None
    print(
        f"catalog demo OK - {catalogs['count']} catalogs, {catalogs['pages']} pages, "
        f"{catalogs['stale']} stale"
    )


if __name__ == "__main__":
    serve("catalog", TOOLS, HANDLERS, demo=_demo)
