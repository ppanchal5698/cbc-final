"""The historian: the agent that turns approved bids into what the next bid can use.

It runs by itself after every sync and every learned bid. From the bids the
curator recorded it counts, in code:

- `(Customer)-[:BUYS]->(CatalogItem)` - what the customer's approved bids were
  priced as, in how many bids, and when last;
- `(Customer)-[:MARGIN_IN]->(Section)` - the margin CBC actually bid per section
  for the customer: average, lowest and highest, over how many lines and bids.

Then, within a budget, the model words a customer's record as an `Insight` for
the estimator starting that customer's next bid - rewritten only once the
customer has a bid it has not seen. Every fact the model is given was counted
here; it adds none.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from cbc.modules.memory.domain.questions import SUMMARIZE_CUSTOMER
from cbc.modules.memory.infrastructure import graph
from cbc.modules.ops.api import ai as ops_ai

log = logging.getLogger("cbc.memory")

AI_BUDGET = 10  # customer insights per run

_BUYS = """
    MATCH (cu:Customer)<-[:FOR_BRAND|FOR_GC]-(b:Bid)-[:HAS_SET]->(:HardwareSet)-[:INCLUDES]->(:SpecItem)
          -[p:PRICED_AS]->(c:CatalogItem)
    WHERE p.bid = b.key
    WITH cu, c, count(DISTINCT b) AS bids, max(b.approvedAt) AS lastAt
    MERGE (cu)-[e:BUYS]->(c) SET e.bids = bids, e.lastAt = lastAt, e.reflectedAt = $run"""

_MARGIN_IN = """
    MATCH (cu:Customer)<-[:FOR_BRAND|FOR_GC]-(b:Bid)-[:HAS_SET]->(h:HardwareSet)-[i:INCLUDES]->()
    MATCH (h)-[:IN_SECTION]->(s:Section)
    WHERE i.margin IS NOT NULL
    WITH cu, s, avg(i.margin) AS average, min(i.margin) AS low, max(i.margin) AS high,
         count(i) AS lines, count(DISTINCT b) AS bids
    MERGE (cu)-[e:MARGIN_IN]->(s)
    SET e.avgMargin = round(average, 4), e.low = low, e.high = high, e.lines = lines, e.bids = bids,
        e.reflectedAt = $run"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _facts(customer: str) -> dict[str, Any]:
    """Everything the graph counted about one customer - and nothing else."""
    [who] = await graph.read(
        "MATCH (cu:Customer {key: $key}) RETURN cu.name AS name, cu.specialMargin AS specialMargin, "
        "cu.specialMarginNote AS specialMarginNote", key=customer)
    bids = await graph.read(
        """MATCH (:Customer {key: $key})<-[r:FOR_BRAND|FOR_GC]-(b:Bid)
           RETURN b.code AS code, b.name AS name, CASE type(r) WHEN 'FOR_BRAND' THEN 'brand' ELSE 'gc' END AS as,
                  b.approvedAt AS approvedAt, b.total AS total, b.margin AS margin, b.lineCount AS lines
           ORDER BY b.approvedAt DESC LIMIT 20""", key=customer)
    parts = await graph.read(
        """MATCH (:Customer {key: $key})-[e:BUYS]->(c:CatalogItem)
           RETURN c.vendor AS vendor, c.part AS part, c.description AS description, e.bids AS bids
           ORDER BY e.bids DESC, e.lastAt DESC LIMIT 25""", key=customer)
    margins = await graph.read(
        """MATCH (:Customer {key: $key})-[e:MARGIN_IN]->(s:Section)
           RETURN s.key AS section, s.title AS title, e.avgMargin AS average, e.low AS low,
                  e.high AS high, e.lines AS lines, e.bids AS bids ORDER BY s.key""", key=customer)
    return {**who, "bids": bids, "partsPricedAs": parts, "marginBySection": margins}


async def _summarize(budget: int, run: str) -> int:
    due = await graph.read(
        """MATCH (cu:Customer)<-[:FOR_BRAND|FOR_GC]-(b:Bid)
           WITH cu, count(DISTINCT b) AS bids, max(b.learnedAt) AS lastLearned
           OPTIONAL MATCH (i:Insight {key: 'customer:' + cu.key})
           WITH cu, bids, lastLearned, i
           WHERE i IS NULL OR i.bidCount <> bids OR i.lastLearned <> lastLearned
           RETURN cu.key AS key, bids, lastLearned ORDER BY bids DESC LIMIT $budget""",
        budget=budget,
    )
    written = 0
    for customer in due:
        facts = await _facts(customer["key"])
        prompt = f"Customer: {facts['name']}\nFacts (JSON): {json.dumps(facts, default=str)}"
        try:
            asked = await ops_ai.ask(SUMMARIZE_CUSTOMER, prompt)
        except Exception as exc:  # no provider: the counted links stand without the words
            asked = None
            log.warning("historian could not ask about %s: %s", customer["key"], exc)
        if asked is None or asked.answer is None:
            break
        answer = asked.answer
        await graph.write(
            """MERGE (i:Insight {key: 'customer:' + $customer})
               SET i.kind = 'customer', i.customer = $customer, i.summary = $summary,
                   i.patterns = $patterns, i.cautions = $cautions, i.bidCount = $bids,
                   i.lastLearned = $lastLearned, i.generatedAt = $run, i.by = $by
               WITH i MATCH (cu:Customer {key: $customer}) MERGE (i)-[:ABOUT]->(cu)""",
            customer=customer["key"], summary=answer.summary, patterns=answer.patterns,
            cautions=answer.cautions, bids=customer["bids"], lastLearned=customer["lastLearned"],
            run=run, by=f"{SUMMARIZE_CUSTOMER.name}@v{SUMMARIZE_CUSTOMER.version}",
        )
        written += 1
    return written


async def reflect(*, budget: int = AI_BUDGET) -> dict[str, int]:
    """Recount what every customer's bids show, then word what changed."""
    run = _now()
    await graph.write(_BUYS, run=run)
    await graph.write(_MARGIN_IN, run=run)
    # A bid forgotten or re-learned differently takes its counts with it.
    await graph.write("MATCH (:Customer)-[e:BUYS|MARGIN_IN]->() WHERE e.reflectedAt <> $run DELETE e", run=run)
    await graph.write(
        """MATCH (i:Insight {kind: 'customer'})
           WHERE NOT EXISTS { (:Customer {key: i.customer})<-[:FOR_BRAND|FOR_GC]-(:Bid) }
           DETACH DELETE i""")
    [customers] = await graph.read(
        "MATCH (cu:Customer) WHERE EXISTS { (cu)<-[:FOR_BRAND|FOR_GC]-(:Bid) } RETURN count(cu) AS n")
    insights = await _summarize(budget, run) if budget > 0 else 0
    await graph.write(
        "MERGE (m:Meta {key: 'historian'}) SET m.lastRunAt = $run, m.customers = $customers, m.insights = $insights",
        run=run, customers=customers["n"], insights=insights,
    )
    return {"customers": customers["n"], "insights": insights}
