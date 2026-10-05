"""The memory curator: the agent that keeps the graph.

It runs by itself - a sync when the API starts and on a timer, a learning pass
whenever an estimator approves a proposal - and it writes two kinds of fact:

- **Mirrored:** vendors, multipliers, price books, catalog items, customers and
  every reference family (frame depths, FRP constants, finishes, tax, special
  nets, margin bands), connected. Rebuilt from DocumentDB on every sync; a row
  removed there is removed here.
- **Learned:** each approved bid - who it was for, its sets, what every spec line
  was priced as, and the workflow that produced it - plus every match an
  estimator confirmed (FR-13). Learned facts accumulate; that is how the graph
  gets more useful with each bid.

It never invents a relationship. Every node and edge traces to a document or an
estimator's decision, because a memory that guessed would teach the next bid the
guess.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from cbc.modules.catalog.api import learning, products
from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.memory.domain import projection
from cbc.modules.memory.infrastructure import graph
from cbc.modules.ops.api import jobs as ops_jobs
from cbc.modules.pricing.api import reference_store
from cbc.modules.projects.api import lookup
from cbc.modules.quoting.api import approvals, lines as quoting_lines

log = logging.getLogger("cbc.memory")

BATCH = 1000
SYNC_INTERVAL_SECONDS = int(os.environ.get("MEMORY_SYNC_INTERVAL_SECONDS", "21600"))  # 6 h


class GraphUnavailable(RuntimeError):
    """Neo4j could not be reached. Transient: the job retries."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _batched(query: str, rows: list[dict[str, Any]], **params: Any) -> int:
    for start in range(0, len(rows), BATCH):
        await graph.write(query, rows=rows[start : start + BATCH], **params)
    return len(rows)


# ── mirrored ─────────────────────────────────────────────────────────────────

_MERGE = {
    "vendors": "UNWIND $rows AS r MERGE (n:Vendor {key: r.key}) SET n += r, n.syncedAt = $run",
    "multipliers": """
        UNWIND $rows AS r
        MERGE (n:Multiplier {key: r.key}) SET n += r, n.syncedAt = $run
        MERGE (v:Vendor {key: r.vendor}) MERGE (v)-[:HAS_MULTIPLIER]->(n)""",
    "books": """
        UNWIND $rows AS r
        MERGE (n:PriceBook {key: r.key}) SET n += r, n.syncedAt = $run
        WITH n, r WHERE r.vendor <> ''
        MERGE (v:Vendor {key: r.vendor}) MERGE (n)-[:PUBLISHED_BY]->(v)""",
    "catalog": """
        UNWIND $rows AS r
        MERGE (n:CatalogItem {key: r.key}) SET n += r, n.syncedAt = $run, n.retired = false
        FOREACH (_ IN CASE WHEN r.vendor <> '' THEN [1] ELSE [] END |
            MERGE (v:Vendor {key: r.vendor}) MERGE (n)-[:MADE_BY]->(v))
        WITH n, r WHERE r.priceBook IS NOT NULL
        MATCH (b:PriceBook {key: r.priceBook}) MERGE (n)-[:LISTED_IN]->(b)""",
    "customers": """
        UNWIND $rows AS r
        MERGE (n:Customer {key: r.key}) SET n += r, n.syncedAt = $run
        WITH n MATCH (f:ReferenceFamily {key: 'special_customer_margins'}) MERGE (f)-[:DEFINES]->(n)""",
    "families": "UNWIND $rows AS r MERGE (n:ReferenceFamily {key: r.key}) SET n += r, n.syncedAt = $run",
}

# Reference entries: label, the family that defines them, and whether they belong
# to a vendor.
_REFERENCE = (
    ("FrameDepth", "frame_depths", False),
    ("FrpConstant", "frp_constants", False),
    ("Finish", "finishes", False),
    ("TaxRate", "tax", False),
    ("MarginBand", "margins", False),
    ("SpecialNet", "hager_special_nets", True),
)

# Mirrored labels whose stale rows a sync removes. CatalogItem is retired rather
# than deleted - an approved bid priced against it must still point at it.
_PRUNE = ("Multiplier", "PriceBook", "ReferenceFamily", "FrameDepth", "FrpConstant",
          "Finish", "TaxRate", "MarginBand", "SpecialNet")


async def sync_all() -> dict[str, Any]:
    """Mirror the record into the graph, then learn any approved bid it has not seen."""
    if not await graph.reachable():
        raise GraphUnavailable("the memory graph is not reachable")
    await graph.ensure_schema()
    run = _now()

    families: dict[str, dict[str, Any]] = {}
    for name in reference_store.list_families_sync():
        try:
            families[name] = await reference_store.get_family(name)
        except KeyError:
            continue

    def family(name: str) -> dict[str, Any]:
        return families.get(name) or {}

    books = await products.price_book_summaries()
    items = [row async for row in products.iter_items()]
    tiers = family("vendor_tiers")

    counts: dict[str, int] = {}
    counts["ReferenceFamily"] = await _batched(_MERGE["families"], projection.family_rows(families), run=run)
    counts["Vendor"] = await _batched(
        _MERGE["vendors"],
        projection.vendor_rows(tiers, books, {i.get("manufacturer") for i in items if i.get("manufacturer")}),
        run=run,
    )
    counts["Multiplier"] = await _batched(_MERGE["multipliers"], projection.multiplier_rows(tiers), run=run)
    counts["PriceBook"] = await _batched(_MERGE["books"], projection.price_book_rows(books), run=run)
    counts["CatalogItem"] = await _batched(_MERGE["catalog"], projection.catalog_rows(items), run=run)
    counts["Customer"] = await _batched(
        _MERGE["customers"], projection.customer_rows(family("special_customer_margins")), run=run
    )
    rows_for = {
        "FrameDepth": projection.frame_depth_rows(family("frame_depths")),
        "FrpConstant": projection.frp_rows(family("frp_constants")),
        "Finish": projection.finish_rows(family("finishes")),
        "TaxRate": projection.tax_rows(family("tax")),
        "MarginBand": projection.margin_band_rows(family("margins")),
        "SpecialNet": projection.special_net_rows(family("hager_special_nets")),
    }
    for label, family_name, by_vendor in _REFERENCE:
        query = f"""
            UNWIND $rows AS r
            MERGE (n:{label} {{key: r.key}}) SET n += r, n.syncedAt = $run
            WITH n, r MATCH (f:ReferenceFamily {{key: $family}}) MERGE (f)-[:DEFINES]->(n)"""
        if by_vendor:
            query += " WITH n, r MERGE (v:Vendor {key: r.vendor}) MERGE (n)-[:FROM_VENDOR]->(v)"
        counts[label] = await _batched(query, rows_for[label], run=run, family=family_name)
    # A special net and the catalog part it prices. Joined on the vendor's item
    # code - the catalog's `part` for Hager - not the model, which every finish
    # of a lock shares.
    await graph.write("""
        MATCH (s:SpecialNet) MATCH (c:CatalogItem {vendor: s.vendor, part: s.itemCode})
        MERGE (s)-[:NET_PRICE_FOR]->(c)""")

    learned = projection.learned_rows([row async for row in learning.confirmed()])
    counts["confirmedMatches"] = await _batched("""
        UNWIND $rows AS r
        MERGE (s:SpecItem {key: r.specKey}) SET s.spec = coalesce(s.spec, r.spec)
        WITH s, r MATCH (c:CatalogItem {key: r.itemKey})
        MERGE (s)-[e:CONFIRMED_AS]->(c)
        SET e.confirmCount = r.confirmCount, e.rejectCount = r.rejectCount,
            e.lastConfirmedAt = r.lastConfirmedAt, e.lastConfirmedBy = r.lastConfirmedBy,
            e.syncedAt = $run""", learned, run=run)

    # What the record no longer holds, the mirror no longer holds.
    for label in _PRUNE:
        await graph.write(f"MATCH (n:{label}) WHERE n.syncedAt <> $run DETACH DELETE n", run=run)
    await graph.write("MATCH (n:CatalogItem) WHERE n.syncedAt <> $run SET n.retired = true", run=run)
    await graph.write("MATCH ()-[e:CONFIRMED_AS]->() WHERE e.syncedAt <> $run DELETE e", run=run)
    await graph.write(
        "MATCH (n:Customer) WHERE n.syncedAt <> $run SET n.specialMargin = null, n.specialMarginNote = null",
        run=run,
    )

    learned_bids = 0
    for project_id in await approvals.approved_project_ids():
        known = await graph.read("MATCH (b:Bid {key: $key}) RETURN b.learnedAt AS at", key=str(project_id))
        if not known:
            if await learn_bid(project_id):
                learned_bids += 1
    counts["bidsLearned"] = learned_bids

    await graph.write(
        "MERGE (m:Meta {key: 'sync'}) SET m.lastSyncAt = $run, m.counts = $counts",
        run=run, counts=[f"{k}={v}" for k, v in sorted(counts.items())],
    )
    return counts


# ── learned ──────────────────────────────────────────────────────────────────

_FORGET_BID = """
    MATCH (b:Bid {key: $key})
    OPTIONAL MATCH (b)-[:HAS_SET]->(s:HardwareSet)
    OPTIONAL MATCH (b)-[:RAN]->(w:WorkflowStep)
    DETACH DELETE s, w"""

_LEARN_ITEMS = """
    UNWIND $rows AS i
    MATCH (h:HardwareSet {key: i.set})
    MERGE (s:SpecItem {key: i.specKey}) ON CREATE SET s.spec = i.spec
    CREATE (h)-[r:INCLUDES]->(s) SET r = i
    WITH s, i
    OPTIONAL MATCH (exact:CatalogItem {key: i.itemKey})
    OPTIONAL MATCH (byPart:CatalogItem {part: i.part}) WHERE i.itemKey IS NULL
    WITH s, i, exact, collect(byPart) AS candidates
    WITH s, i, coalesce(exact, CASE WHEN size(candidates) = 1 THEN candidates[0] END) AS item
    WHERE item IS NOT NULL
    CREATE (s)-[:PRICED_AS {bid: $bid, cost: i.cost, costSource: i.costSource,
                            margin: i.margin, at: $at}]->(item)"""


async def learn_bid(project_id: Any) -> bool:
    """Record one approved bid. Idempotent: a re-approved bid replaces what was learned."""
    if not await graph.reachable():
        raise GraphUnavailable("the memory graph is not reachable")
    approval = await approvals.approval_for(project_id)
    project = await lookup.get(project_id)
    if approval is None or project is None:
        return False
    await graph.ensure_schema()
    rows = projection.bid_rows(
        project,
        approval,
        list(await quoting_lines.list_for_project(project_id)),
        list(await extraction_openings.list_for_project(project_id)),
        await ops_jobs.history_for_project(project_id),
        learning.spec_key,
    )
    bid = rows["bid"]
    key = bid["key"]

    await graph.write(_FORGET_BID, key=key)
    await graph.write("MATCH ()-[r:PRICED_AS {bid: $key}]->() DELETE r", key=key)
    await graph.write("MERGE (b:Bid {key: $bid.key}) SET b += $bid, b.learnedAt = $at", bid=bid, at=_now())
    for relationship, label, people in (
        ("FOR_BRAND", "Customer", rows["brands"]),
        ("FOR_GC", "Customer", rows["gcs"]),
        ("DESIGNED_BY", "Architect", rows["architects"]),
    ):
        await graph.write(
            f"""MATCH (b:Bid {{key: $key}})
                OPTIONAL MATCH (b)-[old:{relationship}]->() DELETE old
                WITH b UNWIND $rows AS r
                MERGE (c:{label} {{key: r.key}}) ON CREATE SET c.name = r.name
                MERGE (b)-[:{relationship}]->(c)""",
            key=key, rows=people,
        )
    await graph.write(
        """MATCH (b:Bid {key: $key}) UNWIND $rows AS r
           MERGE (h:HardwareSet {key: r.key}) SET h += r MERGE (b)-[:HAS_SET]->(h)""",
        key=key, rows=rows["sets"],
    )
    await _batched(_LEARN_ITEMS, rows["items"], bid=key, at=bid["approvedAt"])
    await graph.write(
        """MATCH (b:Bid {key: $key}) UNWIND $rows AS r
           MERGE (w:WorkflowStep {key: r.key}) SET w += r MERGE (b)-[:RAN]->(w)""",
        key=key, rows=rows["steps"],
    )
    await graph.write(
        """MATCH (b:Bid {key: $key})-[:RAN]->(w:WorkflowStep)
           WITH w ORDER BY w.order WITH collect(w) AS steps
           UNWIND range(0, size(steps) - 2) AS i
           WITH steps[i] AS a, steps[i + 1] AS z MERGE (a)-[:NEXT]->(z)""",
        key=key,
    )
    log.info("memory learned %s: %d line(s), %d set(s), %d step(s)",
             bid.get("code"), len(rows["items"]), len(rows["sets"]), len(rows["steps"]))
    return True
