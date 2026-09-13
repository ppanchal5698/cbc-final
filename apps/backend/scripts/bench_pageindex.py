#!/usr/bin/env python3
"""Measure PageIndex retrieval before optimising it.

    python scripts/bench_pageindex.py --catalogs 10 50 100 200

`query.find_pages` fetches every catalog document and ranks in Python, one round
trip per catalog. That is the right shape at today's size and stops being it
somewhere around 50 catalogs - but "somewhere around" is a guess, and the point of
this script is to replace the guess with a number before anyone rewrites the
ranker.

Three variants are timed against the same synthetic corpus:

  current    list_catalogs, then one `get` per catalog, then rank in Python
  projected  the same, fetching only the fields the ranker reads
  one_query  a single `find` over the collection, then rank in Python

The Mongo `$text` option is deliberately not here: it changes the ranking rather
than the fetch, so it cannot be judged on time alone - the scoring tests have to
say whether the new order is as good. Measure the fetch first; it may be that
fixing the N+1 is enough and the ranking never has to move.

Writes into a throwaway database and drops it afterwards.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from cbc.shared.config import settings  # noqa: E402
from cbc.modules.catalog.api.pageindex import query, store  # noqa: E402
from cbc.modules.catalog.api.pageindex.models import PageIndexDocument  # noqa: E402

BENCH_DB = "cbc_bench_pageindex"

# Roughly a real vendor book: a few hundred pages, most of them carrying prices.
PAGES_PER_CATALOG = 200

QUERIES = [
    "Hager 3400 lockset",
    "door closer aluminum finish",
    "threshold saddle 36",
    "exit device rim panic",
    "toilet partition bracket",
]


def _document(index: int) -> PageIndexDocument:
    vendor = f"vendor{index % 12}"
    return PageIndexDocument(
        catalog_id=f"bench-{index:04d}",
        vendor=vendor,
        file_name=f"{vendor}_price_book_{index}.pdf",
        file_hash=f"{index:064x}",
        price_basis="list",
        page_count=PAGES_PER_CATALOG,
        pages=[
            {
                "pdf_page": page,
                "printed_page": str(page),
                "sells": f"{vendor} locksets closers thresholds exit devices page {page}",
                "part_families": [f"{vendor.upper()}-{page}00", f"3400-{page}"],
                "has_prices": page % 3 != 0,
            }
            for page in range(1, PAGES_PER_CATALOG + 1)
        ],
    )


async def _seed(count: int) -> None:
    collection = store._collection()
    await collection.delete_many({})
    for index in range(count):
        await store.save(_document(index))
    await store.ensure_indexes()


async def _current() -> None:
    for q in QUERIES:
        await query.find_pages(q, limit=8)


async def _projected() -> None:
    """Same shape, but without dragging back fields the ranker never reads."""
    collection = store._collection()
    for q in QUERIES:
        documents = []
        async for raw in collection.find({}, {"pages.text": 0, "pages.notes": 0}):
            documents.append(PageIndexDocument.from_mongo(raw))
        query.rank_pages(documents, q, limit=8)


async def _one_query() -> None:
    """The N+1 removed: one find rather than list-then-get-each."""
    collection = store._collection()
    for q in QUERIES:
        documents = [PageIndexDocument.from_mongo(raw) async for raw in collection.find({})]
        query.rank_pages(documents, q, limit=8)


VARIANTS = {"current": _current, "projected": _projected, "one_query": _one_query}


async def _time(fn, rounds: int) -> tuple[float, float]:
    timings = []
    for _ in range(rounds):
        started = time.perf_counter()
        await fn()
        timings.append((time.perf_counter() - started) * 1000 / len(QUERIES))
    return statistics.median(timings), min(timings)


async def run(counts: list[int], rounds: int) -> int:
    from cbc.shared import mongo as db_module

    previous, settings.mongodb_db = settings.mongodb_db, BENCH_DB
    db_module._client = None
    try:
        print(f"{PAGES_PER_CATALOG} pages per catalog, {len(QUERIES)} queries, "
              f"median of {rounds} rounds, milliseconds per query\n")
        print(f"{'catalogs':>9}  " + "  ".join(f"{name:>10}" for name in VARIANTS))
        for count in counts:
            await _seed(count)
            row = []
            for fn in VARIANTS.values():
                median, _ = await _time(fn, rounds)
                row.append(f"{median:10.1f}")
            print(f"{count:>9}  " + "  ".join(row))
        print("\nA rewrite needs a number from this table, not an intuition. "
              "See src/cbc/modules/catalog/api/pageindex/README.md for what each variant changes.")
    finally:
        client = db_module.client()
        await client.drop_database(BENCH_DB)
        settings.mongodb_db = previous
        db_module._client = None
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogs", nargs="+", type=int, default=[10, 50, 100, 200])
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    return asyncio.run(run(args.catalogs, args.rounds))


if __name__ == "__main__":
    sys.exit(main())
