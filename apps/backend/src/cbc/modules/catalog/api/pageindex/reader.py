"""Reading the page index from a synchronous process, with no write access.

The MCP servers are sync and run inside the Claude Code subprocess, which
`provider.WITHHELD` deliberately denies the root connection string: pymongo is in
the image, so a single Bash call with that URI could write to any collection,
straight past every read-only assertion the tools make about themselves.

So this connects with `MONGODB_READONLY_URI` and nothing else. If that variable
is absent the reader refuses rather than reaching for the writable one - a
pricing pass that can edit the catalog is a worse outcome than a pricing pass
that cannot read it, because the first one fails silently.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from cbc.modules.catalog.domain import partquery
from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR

_client = None

COLLECTION = "pageIndex"


class ReadOnlyIndexUnavailable(RuntimeError):
    """No read-only credential, so there is nothing safe to connect with."""


def _collection():
    global _client
    if _client is None:
        uri = os.environ.get("MONGODB_READONLY_URI")
        if not uri:
            raise ReadOnlyIndexUnavailable(
                "MONGODB_READONLY_URI is not set. The catalog server reads the page "
                "index with a credential that cannot write; it will not fall back "
                "to the writable connection string."
            )
        from pymongo import MongoClient

        from cbc.shared.mongo_uri import reachable_uri

        _client = MongoClient(reachable_uri(uri), serverSelectionTimeoutMS=5000)
    return _client[_database_name()][COLLECTION]


def _database_name() -> str:
    """Which database, taken from the connection string that was handed over.

    Not from an environment variable of its own: the URI already names the
    database, and reading the two separately means they can disagree. They did -
    the suite points settings at a test database, the URI followed, and this read
    the default, so every lookup came back empty against a populated index.
    """
    uri = os.environ.get("MONGODB_READONLY_URI", "")
    path = urlsplit(uri).path.lstrip("/").split("?")[0]
    return path or os.environ.get("MONGODB_DB") or "cbc_opshub"


def reset() -> None:
    """Drop the cached client, so a changed connection string is picked up."""
    global _client, _vendor_names
    if _client is not None:
        _client.close()
    _client = None
    _vendor_names = None


def available() -> bool:
    try:
        _collection().database.client.admin.command("ping")
        return True
    except Exception:
        return False


def list_catalogs(vendor: str | None = None) -> list[dict[str, Any]]:
    rows = list(
        _collection()
        .find(_catalog_query(vendor), {"pages": 0, "profile": 0})
        .sort("vendor", 1)
        .limit(200)
    )
    if rows or not vendor:
        return rows
    # Every indexed catalog currently carries vendor "unknown", so a vendor
    # filter matched nothing and find_pages returned no pages at all - while the
    # pricing prompt tells the agent to pass one. An empty result is the shape
    # that became 32 MANUAL lines, so fall back to the whole index rather than
    # answer "no such pages" to a question that has pages.
    return list(
        _collection().find({}, {"pages": 0, "profile": 0}).sort("vendor", 1).limit(200)
    )


def get_catalog(catalog_id: str) -> dict[str, Any] | None:
    return _collection().find_one({"_id": catalog_id})


def all_catalogs(vendor: str | None = None) -> list[dict[str, Any]]:
    """Page documents for ranking, without profile or spreadsheet row ranges."""
    projection = {
        "profile": 0,
        "pages.rows": 0,
        "pages.sheet": 0,
    }
    rows = list(_collection().find(_catalog_query(vendor), projection).limit(50))
    if rows or not vendor:
        return rows
    return list(_collection().find({}, projection).limit(50))  # see list_catalogs


def _items_collection():
    """catalogItems via the same read-only client as pageIndex."""
    return _collection().database["catalogItems"]


def _catalog_query(vendor: str | None) -> dict[str, Any]:
    return {"vendor": vendor.strip().lower()} if vendor else {}


_vendor_names: frozenset[str] | None = None


def vendor_names() -> frozenset[str]:
    """Every vendor token the catalog knows, for stripping one off a part string.

    Cached: `normalize` is called per candidate per line, and this is two
    `distinct` calls over a collection that changes when purchasing uploads a
    sheet, not during a pricing pass. `reset()` clears it.
    """
    global _vendor_names
    if _vendor_names is None:
        try:
            items = _items_collection()
            found = set(items.distinct("vendorKey")) | set(items.distinct("manufacturer"))
        except Exception:
            return frozenset()  # no catalog is not a reason to fail a lookup
        _vendor_names = frozenset(str(v) for v in found if v)
    return _vendor_names


def _learning_collection():
    """matchLearning via the same read-only client. The matcher reads; it never writes."""
    return _collection().database["matchLearning"]


def learned_total() -> int:
    """How many specifications CBC has been taught. 0 when there is no table yet."""
    try:
        return int(_learning_collection().count_documents({}))
    except Exception:
        return 0


def recall_match(spec: str, vendor: str | None = None, *, limit: int = 5) -> list[dict[str, Any]]:
    """What an estimator already decided this specification means (FR-13).

    Exact key first, then similar keys. The similarity pass is `difflib` over one
    org's learned rows, which is a scan - and the right size for it. A learned
    table holds one row per distinct specification an estimator has corrected,
    not one per catalog part, so it is in the hundreds where catalogItems is in
    the thousands.

    ponytail: linear scan over one org's learned rows, fine to ~10k. Index or
    embed only if it shows up in runMetrics.
    """
    key = partquery.spec_key(spec)
    if not key:
        return []

    try:
        rows = list(_learning_collection().find({}).limit(5000))
    except Exception:
        return []  # no learning yet is not a reason to fail a match

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        learned = str(row.get("specKey") or "")
        if not learned:
            continue
        if vendor and vendor.strip():
            manufacturer = str(row.get("manufacturer") or "").lower()
            if vendor.strip().lower() not in manufacturer:
                continue
        score = partquery.similarity(key, learned)
        if score < CONFIDENCE_FLOOR:
            continue
        confirms = int(row.get("confirmCount") or 0)
        rejects = int(row.get("rejectCount") or 0)
        if confirms <= rejects:
            continue  # an estimator has said no to this at least as often as yes
        scored.append((score * (1 + min(confirms, 5) * 0.1), row))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "specified": row.get("specSample"),
            "part": row.get("part"),
            "manufacturer": row.get("manufacturer"),
            "division": row.get("division"),
            "confirmCount": int(row.get("confirmCount") or 0),
            "rejectCount": int(row.get("rejectCount") or 0),
            "lastConfirmedAt": (
                row["lastConfirmedAt"].isoformat()
                if hasattr(row.get("lastConfirmedAt"), "isoformat")
                else row.get("lastConfirmedAt")
            ),
            "lastConfirmedBy": row.get("lastConfirmedBy"),
            "exact": str(row.get("specKey") or "") == key,
        }
        for _, row in scored[: max(1, min(int(limit or 5), 25))]
    ]


def _serialize_item(row: dict[str, Any]) -> dict[str, Any]:
    seed = row.get("seedSource")
    return {
        "part": row.get("part"),
        "model": row.get("model"),
        "description": row.get("description"),
        "manufacturer": row.get("manufacturer"),
        "vendorKey": row.get("vendorKey"),
        "cost": row.get("cost"),
        "listPrice": row.get("listPrice"),
        "multiplier": row.get("multiplier"),
        "defaultMargin": row.get("defaultMargin"),
        "category": row.get("category"),
        "division": row.get("division"),
        "priceBasis": row.get("priceBasis"),
        "seedSource": seed,
        # An ingest row's numbers came off OCR, so it may be matched against but
        # never quoted without re-reading the page it was read from.
        "trusted": seed != partquery.INGEST_SEED,
    }


def lookup_catalog_item(part: str, vendor: str | None = None) -> dict[str, Any] | None:
    """Return a product-catalog row for Path 2b pricing / matching.

    Walks the normalised candidates for `part` - raw string first, then with the
    vendor name and trailing size/finish tokens stripped - trying exact before
    prefix at each step. A schedule cites `PEMKO-275A-42`; the catalog stores
    `275A`. Matching only the raw string missed every composite part number and
    sent the pass to a PDF, which is how a $7.16 threshold was quoted at $12.41.

    Price-book ingest rows are never returned: those numbers were OCR guesses
    and must not be quoted without re-reading the page.
    """
    candidates = partquery.normalize(part, vendor_names())
    if not candidates:
        return None

    items = _items_collection()
    for prefix in (False, True):
        for candidate in candidates:
            query = partquery.identity_filter(candidate, vendor, prefix=prefix)
            if not prefix:
                hit = items.find_one(query)
                if hit is not None:
                    return {**hit, "matchedOn": candidate}
                continue
            # Prefix: a schedule cites a series token (3510) where the catalog
            # holds full models. Shortest part is the closest series match.
            if not partquery.prefix_safe(candidate):
                continue
            rows = list(items.find(query).sort("part", 1).limit(25))
            if rows:
                rows.sort(key=lambda r: (len(str(r.get("part") or "")), str(r.get("part") or "")))
                return {**rows[0], "matchedOn": candidate}
    return None


def search_catalog_items(
    query: str,
    vendor: str | None = None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Ranked product-catalog candidates for matcher Tier 1-3 (before PDF search).

    `$text` against the `product_search` index first. That index has existed all
    along and was never used: the old filter `$or`-ed an unanchored literal
    substring of the *whole* query against `description`, so "paper towel
    dispenser recessed" matched nothing while scanning all 6,579 rows. The regex
    shape survives as the fallback, because `$text` tokenises on word boundaries
    and cannot see a fragment inside `2752WSP`.

    Ingest rows are included here and marked `trusted: false` - a matcher may
    consider one, pricing may not quote it. Hiding them entirely meant the
    pricebook-ingestor wrote rows nothing could ever read.
    """
    needle = str(query or "").strip()
    if not needle:
        return []
    lim = max(1, min(int(limit or 8), 25))
    items = _items_collection()

    rows: list[dict[str, Any]] = []
    try:
        rows = list(
            items.find(
                partquery.text_filter(needle, vendor, include_ingest=True),
                {"score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(lim * 3)
        )
    except Exception:
        rows = []  # no text index on this deployment; the regex below still answers

    if not rows:
        rows = list(
            items.find(partquery.regex_filter(needle, vendor, include_ingest=True))
            .sort("part", 1)
            .limit(lim * 3)
        )

    needle_u = needle.upper()

    def score(row: dict[str, Any]) -> tuple[int, int, int, str]:
        part = str(row.get("part") or "")
        model = str(row.get("model") or "")
        part_u, model_u = part.upper(), model.upper()
        if part_u == needle_u or model_u == needle_u:
            tier = 0
        elif part_u.startswith(needle_u) or model_u.startswith(needle_u):
            tier = 1
        else:
            tier = 2
        # A quotable row outranks an OCR extract at the same tier.
        untrusted = 1 if row.get("seedSource") == partquery.INGEST_SEED else 0
        return (tier, untrusted, len(part), part_u)

    rows.sort(key=score)
    return [_serialize_item(row) for row in rows[:lim]]
