"""The memory curator against a real Neo4j: mirror, prune, learn, recall.

Needs a throwaway Neo4j - by default bolt://localhost:27687, password
`pytest_graph_pw`:

    docker run -d --rm --name cbc-pytest-neo4j -p 127.0.0.1:27687:7687 \
        -e NEO4J_AUTH=neo4j/pytest_graph_pw neo4j:5.26-community

The curator's sources are the other modules' APIs; here they are handed fixed
documents, so these tests exercise the graph and nothing else. Skipped without
the container.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import pytest
from bson import ObjectId

from cbc.modules.catalog.api.learning import spec_key
from cbc.modules.memory.api import curator, recall
from cbc.modules.memory.features import LearnFromBid, SyncMemory
from cbc.modules.memory.infrastructure import graph

URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:27687")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD", "pytest_graph_pw")


def run(coro):
    async def scoped():
        try:
            return await coro
        finally:
            await graph.close()  # one driver per event loop

    return asyncio.run(scoped())


@pytest.fixture()
def neo(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", URI)
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", PASSWORD)
    graph._driver = None
    if not run(graph.reachable()):
        pytest.skip(f"no throwaway Neo4j at {URI}")
    run(graph.write("MATCH (n) DETACH DELETE n"))
    yield
    run(graph.write("MATCH (n) DETACH DELETE n"))


FAMILIES: dict[str, Any] = {
    "vendor_tiers": {"vendors": [
        {"key": "hager", "name": "Hager", "tier": "Hager Advantage Program", "effective_date": "2026-03-02",
         "categories": {"locks": 0.29, "architectural_hinges": 0.21}},
        {"key": "national_guard", "name": "National Guard", "multiplier": 0.45},
        {"key": "pemko", "name": "Pemko", "categories": {"standard": 0.48, "continuous_hinges": 0.33}},
        {"key": "world_dryer", "name": "World Dryer", "multiplier": 0.339},
    ]},
    "special_customer_margins": {"customers": [{"name": "Wendys", "margin": None, "note": "via Banner"}]},
    "frame_depths": {"wall_types": [{"type": "masonry", "depth": "5-3/4", "depth_inches": 5.75}]},
    "frp_constants": {"status": "PENDING", "panel_size": None, "waste_pct": None},
    "finishes": {"finishes": [{"us_code": "US26D", "numeric_code": "626", "description": "Satin chrome"}]},
    "tax": {"rates": {"OH": 0.08}},
    "margins": {"bands": [{"key": "commodity", "name": "Commodity Door Hardware", "margin": 0.27}],
                "accessories_derived": 0.56},
    "hager_special_nets": {"vendor": "hager", "effective_date": "2026-03-02",
                           "items": [{"item_code": "000091", "part_number": "3553", "net_price": 64.58}]},
}
BOOK_ID = ObjectId()


def _sources(monkeypatch, *, families=None, items=None, approved=None, projects=None,
             approvals_by_id=None, lines=None, learned=None):
    families = FAMILIES if families is None else families
    items = items if items is not None else [
        {"part": "BB1279", "manufacturer": "Hager", "cost": 24.5, "priceBookId": BOOK_ID,
         "division": "08 71 00", "priceBasis": "net"},
        {"part": "000091", "manufacturer": "Hager", "model": "3553", "cost": 70.0,
         "division": "08 71 00", "priceBasis": "net"},
        {"part": "1547A", "manufacturer": "Pemko", "cost": 12.9, "division": "08 71 00",
         "category": "continuous_hinges", "priceBasis": "list_x_multiplier", "multiplier": 0.48},
        {"part": "CHS83", "manufacturer": "Pemko", "division": "08 71 00",
         "category": "continuous_hinges", "priceBasis": "list_x_multiplier"},
        {"part": "VERDEdri", "manufacturer": "World Dryer", "division": "10 28 13",
         "priceBasis": "list_x_multiplier"},
    ]

    async def get_family(name):
        return families[name]

    async def gen(rows):
        for row in rows:
            yield row

    async def value(v):
        return v

    monkeypatch.setattr(curator.reference_store, "list_families_sync", lambda: list(families))
    monkeypatch.setattr(curator.reference_store, "get_family", get_family)
    monkeypatch.setattr(curator.products, "price_book_summaries",
                        lambda: value([{"_id": BOOK_ID, "vendor": "hager", "program": "Hager #18"}]))
    monkeypatch.setattr(curator.products, "iter_items", lambda: gen(items))
    monkeypatch.setattr(curator.learning, "confirmed", lambda: gen(learned or []))
    monkeypatch.setattr(curator.approvals, "approved_project_ids", lambda: value(list(approved or [])))
    monkeypatch.setattr(curator.approvals, "approval_for", lambda pid: value((approvals_by_id or {}).get(pid)))
    monkeypatch.setattr(curator.lookup, "get", lambda pid: value((projects or {}).get(pid)))
    monkeypatch.setattr(curator.quoting_lines, "list_for_project", lambda pid: value(list(lines or [])))
    monkeypatch.setattr(curator.extraction_openings, "list_for_project", lambda pid: value([{"mark": "101"}]))
    monkeypatch.setattr(curator.ops_jobs, "history_for_project", lambda pid: value([
        {"_id": ObjectId(), "type": "extract_bid_set", "status": "done", "attempts": 1},
        {"_id": ObjectId(), "type": "match_and_price", "status": "done", "attempts": 2},
    ]))


def _count(query: str, **params) -> int:
    rows = run(graph.read(query, **params))
    return rows[0]["n"] if rows else 0


def test_a_sync_mirrors_vendors_multipliers_customers_catalog_and_reference_data(neo, monkeypatch):
    _sources(monkeypatch, learned=[{"specKey": spec_key("Hager BB1279"), "specSample": "Hager BB1279",
                                    "part": "BB1279", "manufacturer": "Hager", "confirmCount": 2}])
    counts = run(curator.sync_all())
    assert counts["CatalogItem"] == 5 and counts["Multiplier"] == 6

    assert _count("MATCH (:Vendor {key:'hager'})-[:HAS_MULTIPLIER]->(m:Multiplier {category:'locks', value:0.29}) RETURN count(m) AS n") == 1
    assert _count("MATCH (:Vendor {key:'national_guard'})-[:HAS_MULTIPLIER]->(m {category:'all'}) RETURN count(m) AS n") == 1
    assert _count("MATCH (c:CatalogItem {key:'hager:BB1279'})-[:MADE_BY]->(:Vendor {key:'hager'}) MATCH (c)-[:LISTED_IN]->(:PriceBook) RETURN count(c) AS n") == 1
    assert _count("MATCH (:ReferenceFamily {key:'special_customer_margins'})-[:DEFINES]->(c:Customer {key:'wendys'}) RETURN count(c) AS n") == 1
    assert _count("MATCH (:ReferenceFamily {key:'frame_depths'})-[:DEFINES]->(d:FrameDepth {inches:5.75}) RETURN count(d) AS n") == 1
    assert _count("MATCH (:ReferenceFamily {key:'frp_constants'})-[:DEFINES]->(f:FrpConstant) RETURN count(f) AS n") == 2
    assert _count("MATCH (:SpecialNet {itemCode:'000091'})-[:NET_PRICE_FOR]->(:CatalogItem {key:'hager:000091'}) RETURN count(*) AS n") == 1
    assert _count("MATCH (:SpecItem)-[e:CONFIRMED_AS {confirmCount:2}]->(:CatalogItem {key:'hager:BB1279'}) RETURN count(e) AS n") == 1


def test_a_second_sync_changes_nothing_and_a_removed_row_leaves_the_mirror(neo, monkeypatch):
    _sources(monkeypatch)
    run(curator.sync_all())
    nodes = _count("MATCH (n) RETURN count(n) AS n")
    run(curator.sync_all())
    assert _count("MATCH (n) RETURN count(n) AS n") == nodes

    fewer = dict(FAMILIES)
    fewer["vendor_tiers"] = {"vendors": [{"key": "hager", "name": "Hager", "categories": {"locks": 0.29}}]}
    _sources(monkeypatch, families=fewer, items=[{"part": "BB1279", "manufacturer": "Hager"}])
    run(curator.sync_all())
    assert _count("MATCH (m:Multiplier) RETURN count(m) AS n") == 1
    # A catalog part an approved bid may point at is retired, never deleted.
    assert _count("MATCH (c:CatalogItem {key:'pemko:1547A', retired:true}) RETURN count(c) AS n") == 1


def test_an_approved_bid_is_learned_once_and_recalled_for_the_next_bid_of_that_brand(neo, monkeypatch):
    pid = ObjectId()
    approved_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    lines = [
        {"group": "SET 01", "part": "BB1279", "manufacturer": "Hager", "description": "HINGE 4.5x4.5",
         "qty": 3, "cost": 24.5, "costSource": "LIST_X_MULTIPLIER", "margin": 0.27, "division": "08 71 00"},
        {"group": "SET 01", "part": "1547A", "manufacturer": None, "description": "THRESHOLD",
         "qty": 1, "cost": 12.9, "costSource": "CATALOG_BASELINE", "margin": 0.27, "division": "08 71 00"},
        {"group": "SET 02", "part": None, "manufacturer": None, "description": "WALL STOP",
         "qty": 1, "cost": None, "costSource": "MANUAL", "addedByHand": True},
    ]
    _sources(
        monkeypatch,
        approved=[pid],
        projects={pid: {"_id": pid, "code": "CBC-1", "name": "Wendys Acheson", "brand": "Wendys", "gc": "Acme"}},
        approvals_by_id={pid: {"approvedBy": "kevin@cbc.com", "approvedAt": approved_at,
                               "totalsSnapshot": {"grandTotal": 1200.0, "margin": 0.27}}},
        lines=lines,
    )
    counts = run(curator.sync_all())
    assert counts["bidsLearned"] == 1

    assert _count("MATCH (b:Bid {code:'CBC-1', approvedBy:'kevin@cbc.com'})-[:FOR_BRAND]->(:Customer {key:'wendys'}) RETURN count(b) AS n") == 1
    assert _count("MATCH (:Bid {code:'CBC-1'})-[:HAS_SET]->(h:HardwareSet) RETURN count(h) AS n") == 2
    assert _count("MATCH (:HardwareSet)-[i:INCLUDES]->(:SpecItem) RETURN count(i) AS n") == 3
    # Priced as the catalog part: by vendor and part, or by part alone when only one vendor has it.
    assert _count("MATCH (:SpecItem)-[p:PRICED_AS {bid:$bid}]->(c:CatalogItem) RETURN count(p) AS n", bid=str(pid)) == 2
    assert _count("MATCH (:Bid {code:'CBC-1'})-[:RAN]->(a:WorkflowStep)-[:NEXT]->(z:WorkflowStep) RETURN count(*) AS n") == 1
    assert _count("MATCH (:Bid {code:'CBC-1'})-[e:COVERS {lines: 2}]->(:Section {key:'08 71 00'}) RETURN count(e) AS n") == 1
    assert _count("MATCH (:Bid {code:'CBC-1'})-[:HAS_SET]->(:HardwareSet {name:'SET 01'})-[:IN_SECTION]->(:Section {key:'08 71 00'}) RETURN count(*) AS n") == 1

    # The same approval learned again replaces, it does not duplicate.
    assert run(curator.learn_bid(pid)) is True
    assert _count("MATCH (:HardwareSet)-[i:INCLUDES]->(:SpecItem) RETURN count(i) AS n") == 3
    assert _count("MATCH ()-[p:PRICED_AS]->() RETURN count(p) AS n") == 2

    similar = run(recall.similar_bids({"_id": ObjectId(), "brand": "Wendys", "gc": "Someone else"}))
    assert [b["code"] for b in similar] == ["CBC-1"]
    assert sorted(similar[0]["sets"]) == ["SET 01", "SET 02"]
    found = run(recall.resolutions([spec_key("Hager BB1279 HINGE 4.5x4.5")]))
    [hinge] = found[spec_key("Hager BB1279 HINGE 4.5x4.5")]
    assert hinge["itemKey"] == "hager:BB1279" and hinge["priced"] == 1 and hinge["bids"] == [str(pid)]

    summary = run(recall.summary())
    assert summary["available"] and summary["nodes"]["Bid"] == 1 and summary["recentBids"][0]["code"] == "CBC-1"
    assert "CBC-1" in run(recall.prompt_block({"_id": ObjectId(), "brand": "Wendys"}))


def test_without_a_graph_recall_is_empty_and_an_approval_queues_nothing(monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    graph._driver = None
    assert run(recall.similar_bids({"_id": ObjectId(), "brand": "Wendys"})) == []
    assert run(recall.summary()) == {"available": False, "configured": False}
    queued: list = []

    async def enqueue(*args, **kwargs):
        queued.append(kwargs)

    monkeypatch.setattr(LearnFromBid.jobs, "enqueue", enqueue)
    run(LearnFromBid.on_proposal_approved(ObjectId(), approved_by="kevin@cbc.com"))
    assert queued == []
    monkeypatch.setenv("NEO4J_URI", URI)
    run(LearnFromBid.on_proposal_approved(ObjectId("6ac2c151308ad1cf03889099"), approved_by="kevin@cbc.com"))
    assert queued == [{"payload": {"projectId": "6ac2c151308ad1cf03889099"}, "actor": "memory-curator"}]


def test_the_timer_queues_a_sync_only_when_one_is_due(neo, monkeypatch):
    """Never synced: due. Just synced: not due until the interval passes."""
    _sources(monkeypatch)
    assert run(SyncMemory.sync_due()) is True
    run(curator.sync_all())
    assert run(SyncMemory.sync_due()) is False
    monkeypatch.setattr(curator, "SYNC_INTERVAL_SECONDS", 0)
    assert run(SyncMemory.sync_due()) is True


def test_catalog_parts_sit_in_their_division_and_link_to_what_prices_them(neo, monkeypatch):
    _sources(monkeypatch)
    run(curator.sync_all())
    # Part -> section -> parent section -> division.
    assert _count("""MATCH (:CatalogItem {key:'world_dryer:VERDEdri'})-[:IN_SECTION]->(:Section {key:'10 28 13'})
                     -[:PART_OF]->(:Section {key:'10 28 00'})-[:PART_OF]->(d:Division {key:'10', title:'Specialties'})
                     RETURN count(d) AS n""") == 1
    assert _count("MATCH (:CatalogItem)-[:IN_SECTION]->(s:Section {key:'08 71 00', title:'Door Hardware'}) RETURN count(*) AS n") == 4
    # The section's margin band, as pricing applies it.
    assert _count("MATCH (:Section {key:'10 28 13'})-[e:DEFAULT_MARGIN_BAND {fallback:false}]->(:MarginBand {key:'accessories', margin:0.56}) RETURN count(e) AS n") == 1
    assert _count("MATCH (:Section {key:'08 71 00'})-[:DEFAULT_MARGIN_BAND]->(:MarginBand {key:'commodity'}) RETURN count(*) AS n") == 1
    # The multiplier that prices a list-priced part: the one its row was priced
    # at, even where its category label points elsewhere (and the link says so).
    assert _count("MATCH (:CatalogItem {key:'pemko:1547A'})-[:PRICED_BY {how:'row_multiplier', categoryAgrees:false}]->(:Multiplier {key:'pemko:standard'}) RETURN count(*) AS n") == 1
    # With no multiplier on the row, the category's tier; a net part takes none.
    assert _count("MATCH (:CatalogItem {key:'pemko:CHS83'})-[:PRICED_BY {how:'category', categoryAgrees:true}]->(:Multiplier {key:'pemko:continuous_hinges'}) RETURN count(*) AS n") == 1
    assert _count("MATCH (:CatalogItem {key:'world_dryer:VERDEdri'})-[:PRICED_BY {how:'account'}]->(:Multiplier {key:'world_dryer:all'}) RETURN count(*) AS n") == 1
    assert _count("MATCH (:CatalogItem {key:'hager:BB1279'})-[e:PRICED_BY]->() RETURN count(e) AS n") == 0

    # A part moved to another section loses the old link on the next sync.
    moved = [{"part": "VERDEdri", "manufacturer": "World Dryer", "division": "10 28 00",
              "priceBasis": "list_x_multiplier"}]
    _sources(monkeypatch, items=moved)
    run(curator.sync_all())
    assert _count("MATCH (:CatalogItem {key:'world_dryer:VERDEdri'})-[:IN_SECTION]->(s:Section) RETURN collect(s.key)[0] AS n") == "10 28 00"

