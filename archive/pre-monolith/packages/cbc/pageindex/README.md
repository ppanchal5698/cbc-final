# PageIndex

How a run finds a price.

The vendor sheets under `pricebooks/` are the source of truth and nothing
pre-extracts them. The index describes **each page** — what it sells, which part
families are on it, whether it carries prices — and a pricing pass opens that page
and reads the number off it. It routes; the PDF answers.

So no stored value can be stale or wrong about a price, **because no price is
stored**.

## Layout

| Module | What it does |
|---|---|
| `build.py` | Builds a document from a sheet. Idempotent on the file hash |
| `describe.py` | Turns a page into its description |
| `basis.py` | Works out whether a sheet quotes list, net, or a multiplier |
| `profile.py` | Per-vendor quirks |
| `reader.py` | Page text, via `cbc.core` |
| `models.py` | `PageIndexDocument` and friends |
| `store.py` | The `pageIndex` collection in MongoDB |
| `query.py` | Ranking pages against a query |

One JSON document per catalog. Uploading a sheet enqueues `index_catalog`;
deleting one enqueues `delete_catalog` and the cascade drops its document.

```bash
python -m cbc.pageindex.build --all
```

## Why not a product table

This replaced a SQLite FTS5 index that pre-extracted every product row. Vendor
catalogs are too irregular for that: **37.8%** of the codes it produced contained
no letter at all, dates were recorded as part numbers, and one vendor's sheet
yielded nothing while reporting success.

## Scaling limit

`query.find_pages` fetches **every catalog document** and ranks them in Python:

```python
for header in await store.list_catalogs(vendor):
    document = await store.get(header["_id"])   # one round trip per catalog
```

That is one round trip per catalog plus full deserialisation of each, on every
search. It is the right shape at today's size — a dozen catalogs, a few hundred
pages each, and ranking that fits in a few milliseconds — and it keeps the scoring
readable and testable, which matters more than speed while the ranking is still
being tuned.

**It stops being the right shape somewhere around 50 catalogs.** Passing `vendor`
narrows the fetch and is the cheapest mitigation; most pricing lookups already
know their vendor.

Past that, the options in order of effort:

1. **Project the fetch.** `store.get` returns whole documents including page text
   the ranker never reads. Fetching only the ranked fields would cut most of the
   cost without changing the algorithm.
2. **One query instead of N.** `list_catalogs` then `get` per id is an N+1; a
   single `find` over the collection removes the round trips.
3. **A Mongo `$text` index** over page descriptions, ranking server-side. This
   changes the ranking, so it needs the scoring tests to be the arbiter of whether
   the new order is as good.

`scripts/bench_pageindex.py` measures these against the current implementation at
a given catalog count — run it before choosing, not after.

```bash
python scripts/bench_pageindex.py --catalogs 10 50 100 200
```

### Measured, 2026-09-01

200 pages per catalog, median ms per query, local MongoDB:

| catalogs | current | projected | one_query |
|---:|---:|---:|---:|
| 10 | 26.2 | 15.3 | 14.9 |
| 50 | 144.8 | 131.0 | 81.7 |

Two things follow. The cost is **super-linear in catalogs** — 5× the catalogs cost
5.5× the time — and **the N+1 is most of it**: a single `find` is already 44%
faster at 50 catalogs, without touching the ranking at all.

So option 2 is the one to take first, and it is a change to one function. Reach
for a `$text` index only if that is measured to be insufficient — it is the only
option here that changes which pages come back, and correctness of the ranking
matters more than its speed.
