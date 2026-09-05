"""Finding the page to open.

The whole point of the index: turn "what does a Hager 3400 storeroom lock cost"
into "open PDF page 297" without reading 744 pages, and without trusting a
pre-extracted table that may have misread the row.

Scoring is deliberately explainable. A pricing pass that is sent to the wrong
page must be able to see why, and an estimator reviewing a quote must be able to
follow the same trail. There is no embedding here and nothing to re-train.
"""
from __future__ import annotations

import copy
import re
from collections import OrderedDict
from typing import Any

from cbc.pageindex import store
from cbc.pageindex.models import PageEntry, PageIndexDocument

# Where the vendor books live, relative to the repository root - which is what
# pdf-tools resolves against.
PRICEBOOK_DIR = "pricebooks"

_FIND_PAGES_MAX = 256
_api_find_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()


def headers_watermark(headers: list[dict[str, Any]]) -> str:
    """max(builtAt) over catalog headers — cheap invalidation for C-07."""
    if not headers:
        return ""
    return max(str(row.get("builtAt") or "") for row in headers)


def find_pages_cache_key(
    query: str, vendor: str | None, limit: int, watermark: str
) -> tuple:
    return (
        str(query or "").strip().lower(),
        str(vendor or "").strip().lower(),
        int(limit),
        watermark or "",
    )


def clear_find_pages_cache() -> None:
    _api_find_cache.clear()


def _cache_get(key: tuple) -> dict[str, Any] | None:
    hit = _api_find_cache.get(key)
    if hit is None:
        return None
    _api_find_cache.move_to_end(key)
    return copy.deepcopy(hit)


def _cache_put(key: tuple, payload: dict[str, Any]) -> dict[str, Any]:
    _api_find_cache[key] = payload
    _api_find_cache.move_to_end(key)
    while len(_api_find_cache) > _FIND_PAGES_MAX:
        _api_find_cache.popitem(last=False)
    return copy.deepcopy(payload)


# Words that match every page of every price book and so separate nothing.
_STOPWORDS = frozenset(
    """a an and or the for of with to in on at by from price prices list cost
    each item items product products series type size finish""".split()
)


def _terms(query: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9/-]+", query.upper()) if len(t) > 1]


def _looks_like_code(term: str) -> bool:
    """A part number, as opposed to a word. Digits are the giveaway."""
    return any(ch.isdigit() for ch in term)


def score_page(page: PageEntry, terms: list[str]) -> tuple[float, list[str]]:
    """How well one page answers the query, and why.

    Weighted so a part-number hit beats a description word: "3400" appearing in
    the code families of a page is much stronger evidence than "lock" appearing
    in its prose.
    """
    if not terms:
        return 0.0, []

    title = page.title.upper()
    description = page.description.upper()
    prefixes = [c.upper() for c in page.code_prefixes]
    keywords = " ".join(page.keywords).upper()
    score = 0.0
    why: list[str] = []

    for term in terms:
        if term.lower() in _STOPWORDS:
            continue
        # Both directions. The index stores *families* - "this page is where the
        # 4131 series lives" - but a bid asks for a whole part number, and
        # `4131CNBL36` does not start-with-match a stored `4131` the other way
        # round. That asymmetry meant a real code on a real indexed page scored
        # zero, find_pages returned nothing, and the pricing pass - having no
        # page to read - invented a number instead. Family-to-code is the common
        # query, so it is the one that has to work.
        code_hit = any(
            prefix == term or prefix.startswith(term) or term.startswith(prefix)
            for prefix in prefixes
        )
        if code_hit:
            score += 5.0 if _looks_like_code(term) else 2.0
            why.append(f"{term} in part families")
            continue
        if term in title:
            score += 3.0 if _looks_like_code(term) else 2.0
            why.append(f"{term} in title")
            continue
        if term in keywords:
            # What the page actually sells, which is stronger than prose.
            score += 2.5
            why.append(f"{term} in page keywords")
            continue
        if term in description:
            score += 0.5
            why.append(f"{term} in description")

    # The whole phrase, not just its words. "hand dryer" matched a page of
    # surgical glove dispensers as strongly as the page of hand dryers, because
    # both mention both words somewhere; the page that is *about* the thing asked
    # for has to win.
    phrase = " ".join(t for t in terms if t.lower() not in _STOPWORDS)
    if phrase:
        if phrase in title:
            score += 5.0
            why.insert(0, f"page is titled {page.title!r}")
        elif phrase in keywords:
            score += 3.0
            why.insert(0, f"{phrase} is what this page sells")

    # A page that carries prices is the one a pricing pass wants; an item-number
    # listing is where you go to find the code first.
    if score and page.has_prices:
        score += 1.0
    if page.kind == "diagram":
        score *= 0.4
    # A page whose own description is uncertain should not outrank a confident one.
    score *= 0.5 + (page.confidence / 2)
    return round(score, 2), why[:4]


def rank_pages(
    documents: list[PageIndexDocument],
    query: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Score already-fetched catalogs. Pure, and the only place ranking happens.

    Fetching is the caller's job because the two callers are not entitled to the
    same connection: the API reads with the application credential, and the MCP
    server reads with one that cannot write. Putting the fetch in here once meant
    the MCP server reached the database through the writable client - which is
    precisely what `provider.WITHHELD` exists to prevent.
    """
    terms = _terms(query)
    if not terms:
        return {"query": query, "count": 0, "pages": [], "note": "give something to search for"}

    hits: list[dict[str, Any]] = []
    for document in documents:
        for page in document.pages:
            score, why = score_page(page, terms)
            if score <= 0:
                continue
            hits.append(
                {
                    "catalog_id": document.catalog_id,
                    "vendor": document.vendor,
                    "file": document.file_name,
                    # The path pdf-tools takes, not just the name. Handing back a
                    # bare filename left the run to guess the directory, and it
                    # guessed the project's own uploads folder - so the page it
                    # had correctly found could not be opened, and the line went
                    # MANUAL. A tool that names a page should name where it is.
                    "file_path": f"{PRICEBOOK_DIR}/{document.file_name}",
                    "pdf_page": page.pdf_page,
                    "printed_page": page.printed_page,
                    "locator": page.locator(),
                    "title": page.title,
                    "description": page.description,
                    "code_prefixes": page.code_prefixes,
                    "keywords": page.keywords,
                    "has_prices": page.has_prices,
                    **(
                        {
                            "price_columns": page.price_columns,
                            "caution": (
                                "This page prints more than one money column ("
                                + ", ".join(page.price_columns)
                                + "). Read the LIST column. MAP is a minimum "
                                "advertised price - an advertising floor, not a "
                                "cost basis - and on ASI pages it runs about 55% "
                                "of list, so taking it and applying the vendor "
                                "multiplier underquotes the line by half."
                            ),
                        }
                        if page.price_columns
                        else {}
                    ),
                    "kind": page.kind,
                    "price_basis": document.price_basis,
                    "effective_date": document.effective_date,
                    "score": score,
                    "why": why,
                }
            )

    hits.sort(key=lambda h: -h["score"])
    top = hits[:limit]
    return {
        "query": query,
        "count": len(top),
        "total_matched": len(hits),
        "pages": top,
        "note": (
            "Open the page with pdf-tools and read the price off it. These "
            "descriptions route; they do not quote."
            if top
            else "No page matched. That is not proof the part does not exist - it "
                 "may be a MANUAL cut-off item, or in a catalog not indexed yet. "
                 "Do not substitute a similar part."
        ),
    }


async def find_pages(
    query: str,
    *,
    vendor: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Pages worth opening, fetched with the application's own connection."""
    import asyncio

    headers = await store.list_catalogs(vendor)
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

    watermark = headers_watermark(headers)
    key = find_pages_cache_key(query, vendor, limit, watermark)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    documents: list[PageIndexDocument] = []
    for header in headers:
        document = await store.get(header["_id"])
        if document:
            documents.append(document)
    ranked = await asyncio.to_thread(rank_pages, documents, query, limit=limit)
    return _cache_put(key, ranked)


async def get_overview(catalog_id: str) -> dict[str, Any]:
    """What this catalog is, before you go looking for a page in it."""
    document = await store.get(catalog_id)
    if document is None:
        return {"found": False, "catalog_id": catalog_id, "note": "no such catalog"}
    return {
        "found": True,
        "catalog_id": document.catalog_id,
        "vendor": document.vendor,
        "file": document.file_name,
        "kind": document.kind,
        "price_basis": document.price_basis,
        "effective_date": document.effective_date,
        "page_count": document.page_count,
        "summary": document.overview.summary,
        "product_lines": document.overview.product_lines,
        "how_prices_are_shown": document.overview.how_prices_are_shown,
        "gotchas": document.overview.gotchas,
        "how_to_find_a_part": document.overview.how_to_find_a_part,
    }


async def get_page(catalog_id: str, pdf_page: int) -> dict[str, Any]:
    """One page's entry, for confirming a citation before quoting it."""
    document = await store.get(catalog_id)
    if document is None:
        return {"found": False, "note": "no such catalog"}
    for page in document.pages:
        if page.pdf_page == pdf_page:
            return {
                "found": True,
                "catalog_id": document.catalog_id,
                "file": document.file_name,
                "file_path": f"{PRICEBOOK_DIR}/{document.file_name}",
                "pdf_page": page.pdf_page,
                "printed_page": page.printed_page,
                "locator": page.locator(),
                "title": page.title,
                "description": page.description,
                "code_prefixes": page.code_prefixes,
                "has_prices": page.has_prices,
                "kind": page.kind,
                "confidence": page.confidence,
                "price_basis": document.price_basis,
                "effective_date": document.effective_date,
            }
    return {"found": False, "note": f"{catalog_id} has no page {pdf_page}"}
