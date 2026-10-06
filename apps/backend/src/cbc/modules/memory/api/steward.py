"""The steward: the agent that watches the memory graph for what is wrong in it.

It runs by itself after every sync and every learned bid. Each check is a query
in code - what is wrong is never a model's opinion - and each problem becomes a
`Finding` linked to the nodes it is about. A finding the next run no longer sees
was fixed at its source and resolves itself; one an admin dismissed stays
dismissed while it recurs. Then, within a budget, the model explains each new
finding in plain words and suggests the fix. With no model answering, the
findings are still recorded, just not explained yet.

It writes to the graph only. A fix to a price book, a multiplier or reference
data is a person's change in DocumentDB (the core rules); the steward says what
and where, and sees it resolved on the next sync.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from cbc.modules.memory.domain.questions import EXPLAIN_FINDING
from cbc.modules.memory.infrastructure import graph
from cbc.modules.ops.api import ai as ops_ai, freshness

log = logging.getLogger("cbc.memory")

AI_BUDGET = 20  # explanations per run; the rest wait for the next one
_ISO_DATE = r"\d{4}-\d{2}-\d{2}.*"
SEVERITY_ORDER = "CASE f.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"


@dataclass(frozen=True)
class Check:
    key: str
    severity: str  # high | medium | low
    meaning: str  # what it looks for: told to the model, kept on the finding
    # Rows of: instance, count, subjects [{label, key}], details {...}. Every list in
    # the details is ordered: the same facts must read the same, or every run
    # would look like news and be explained again.
    query: str
    summary: Callable[[dict[str, Any], int], str]


def _pct(value: Any) -> str:
    return f" ({value:.0%})" if isinstance(value, (int, float)) else ""


def _tiers(priced_at: list[dict[str, Any]]) -> str:
    return ", ".join(f"{p['tier']} {p['multiplier']} ({p['parts']} parts)" for p in priced_at)


CHECKS: tuple[Check, ...] = (
    Check(
        "category_multiplier_conflict", "high",
        "Catalog rows whose category label points at one vendor multiplier tier while the row "
        "itself was priced at another, so a lookup by category and the row disagree on cost.",
        """MATCH (c:CatalogItem)-[:PRICED_BY {categoryAgrees: false}]->(m:Multiplier)
           MATCH (c)-[:MADE_BY]->(v:Vendor)
           MATCH (labelled:Multiplier {vendor: c.vendor, category: c.category})
           WITH v, labelled, m, count(c) AS parts ORDER BY parts DESC, m.key
           WITH v, labelled, sum(parts) AS parts, collect(m.key) AS tierKeys,
                collect({tier: m.category, multiplier: m.value, parts: parts}) AS pricedAt
           RETURN v.key + ':' + labelled.category AS instance, parts AS count,
                  [{label: 'Vendor', key: v.key}, {label: 'Multiplier', key: labelled.key}]
                    + [k IN tierKeys | {label: 'Multiplier', key: k}] AS subjects,
                  {vendor: v.name, labelledCategory: labelled.category,
                   labelledMultiplier: labelled.value, pricedAt: pricedAt} AS details""",
        lambda d, n: (f"{n} {d['vendor']} parts are labelled {d['labelledCategory']} "
                      f"(multiplier {d['labelledMultiplier']}) but were priced at another tier: "
                      f"{_tiers(d['pricedAt'])}."),
    ),
    Check(
        "list_part_without_multiplier", "high",
        "List-priced catalog parts with no vendor multiplier on record to turn list into cost.",
        """MATCH (c:CatalogItem)
           WHERE c.priceBasis IN ['list_x_multiplier', 'list'] AND NOT coalesce(c.retired, false)
             AND NOT EXISTS { (c)-[:PRICED_BY]->() }
           WITH c ORDER BY c.part
           WITH c.vendor AS vendor, count(c) AS parts, collect(c.part)[..20] AS sample
           OPTIONAL MATCH (v:Vendor {key: vendor})
           RETURN vendor AS instance, parts AS count, [{label: 'Vendor', key: vendor}] AS subjects,
                  {vendor: coalesce(v.name, vendor), parts: sample} AS details""",
        lambda d, n: (f"{n} list-priced {d['vendor'] or 'unbranded'} parts have no multiplier on "
                      f"record, so their cost cannot be worked out from list."),
    ),
    Check(
        "multiplier_past_review", "high",
        "A vendor multiplier sheet older than the price-sheet review window.",
        """MATCH (v:Vendor)-[:HAS_MULTIPLIER]->(m:Multiplier)
           WHERE m.effective =~ $isoDate AND left(m.effective, 10) < $cutoff
           OPTIONAL MATCH (c:CatalogItem)-[:PRICED_BY]->(m)
           WITH v, m, c ORDER BY m.key
           WITH v, min(left(m.effective, 10)) AS effective, collect(DISTINCT m.key) AS tiers, count(c) AS parts
           RETURN v.key AS instance, parts AS count,
                  [{label: 'Vendor', key: v.key}] + [k IN tiers | {label: 'Multiplier', key: k}] AS subjects,
                  {vendor: v.name, effective: effective, reviewDays: $reviewDays} AS details""",
        lambda d, n: (f"{d['vendor']}'s multipliers are dated {d['effective']}, past the "
                      f"{d['reviewDays']}-day review window; {n} catalog parts are priced with them."),
    ),
    Check(
        "price_book_past_review", "high",
        "A vendor price book older than the price-sheet review window.",
        """MATCH (b:PriceBook) WHERE b.effective =~ $isoDate AND left(b.effective, 10) < $cutoff
           OPTIONAL MATCH (c:CatalogItem)-[:LISTED_IN]->(b)
           WITH b, count(c) AS parts
           RETURN b.key AS instance, parts AS count,
                  [{label: 'PriceBook', key: b.key}, {label: 'Vendor', key: b.vendor}] AS subjects,
                  {book: b.name, effective: left(b.effective, 10), reviewDays: $reviewDays} AS details""",
        lambda d, n: (f"{d['book']} is dated {d['effective']}, past the {d['reviewDays']}-day "
                      f"review window; {n} catalog parts are listed in it."),
    ),
    Check(
        "special_net_past_review", "high",
        "Special net prices older than the price-sheet review window.",
        """MATCH (s:SpecialNet) WHERE s.effective =~ $isoDate AND left(s.effective, 10) < $cutoff
           WITH s.vendor AS vendor, min(left(s.effective, 10)) AS effective, count(s) AS nets
           OPTIONAL MATCH (v:Vendor {key: vendor})
           RETURN vendor AS instance, nets AS count, [{label: 'Vendor', key: vendor}] AS subjects,
                  {vendor: coalesce(v.name, vendor), effective: effective, reviewDays: $reviewDays} AS details""",
        lambda d, n: (f"{n} {d['vendor']} special nets are dated {d['effective']}, past the "
                      f"{d['reviewDays']}-day review window."),
    ),
    Check(
        "section_without_band", "medium",
        "A MasterFormat section holding catalog parts that has no margin band of its own, so "
        "pricing gives its parts the default band.",
        """MATCH (s:Section)-[:DEFAULT_MARGIN_BAND {fallback: true}]->(b:MarginBand)
           MATCH (s)<-[:IN_SECTION]-(c:CatalogItem)
           WITH s, b, count(c) AS parts
           RETURN s.key AS instance, parts AS count,
                  [{label: 'Section', key: s.key}, {label: 'MarginBand', key: b.key}] AS subjects,
                  {section: s.key, title: s.title, band: b.key, margin: b.margin} AS details""",
        lambda d, n: (f"{n} catalog parts sit in {d['section']}{' ' + d['title'] if d['title'] else ''}, "
                      f"which has no margin band of its own; pricing gives them the {d['band']} "
                      f"band{_pct(d['margin'])}."),
    ),
    Check(
        "catalog_part_without_section", "medium",
        "Catalog parts whose division is missing or is not a MasterFormat code.",
        """MATCH (c:CatalogItem)
           WHERE NOT coalesce(c.retired, false) AND NOT EXISTS { (c)-[:IN_SECTION]->() }
           WITH c ORDER BY c.part
           WITH c.vendor AS vendor, count(c) AS parts, collect(c.part)[..20] AS sample,
                collect(DISTINCT c.division)[..10] AS divisions
           OPTIONAL MATCH (v:Vendor {key: vendor})
           RETURN vendor AS instance, parts AS count, [{label: 'Vendor', key: vendor}] AS subjects,
                  {vendor: coalesce(v.name, vendor), parts: sample, divisions: divisions} AS details""",
        lambda d, n: (f"{n} {d['vendor'] or 'unbranded'} catalog parts have no recognisable "
                      f"MasterFormat division"
                      + (f" (they say {', '.join(map(str, d['divisions']))})" if d["divisions"] else "") + "."),
    ),
    Check(
        "reference_pending", "medium",
        "Reference data marked pending: values CBC has still to supply.",
        """MATCH (f:ReferenceFamily) WHERE toUpper(coalesce(f.status, '')) CONTAINS 'PENDING'
           OPTIONAL MATCH (f)-[:DEFINES]->(empty:FrpConstant) WHERE empty.value IS NULL
           WITH f, empty ORDER BY empty.key
           WITH f, collect(empty.key) AS missing
           RETURN f.key AS instance, size(missing) AS count,
                  [{label: 'ReferenceFamily', key: f.key}] + [k IN missing | {label: 'FrpConstant', key: k}] AS subjects,
                  {family: f.key, status: f.status, description: f.description, missing: missing} AS details""",
        lambda d, n: (f"Reference data {d['family']} is marked {d['status']}"
                      + (f"; still empty: {', '.join(d['missing'])}" if d["missing"] else "") + "."),
    ),
    Check(
        "conflicting_learning", "medium",
        "One specification that approved bids priced, or estimators confirmed, as different parts.",
        """MATCH (s:SpecItem)-[:PRICED_AS|CONFIRMED_AS]->(c:CatalogItem)
           WITH s, c ORDER BY c.key
           WITH s, collect(DISTINCT c.key) AS items WHERE size(items) > 1
           RETURN s.key AS instance, size(items) AS count,
                  [{label: 'SpecItem', key: s.key}] + [k IN items | {label: 'CatalogItem', key: k}] AS subjects,
                  {spec: s.spec, items: items} AS details""",
        lambda d, n: f"'{d['spec']}' was priced or confirmed as {n} different parts: {', '.join(d['items'])}.",
    ),
    Check(
        "special_net_unlinked", "low",
        "Special net prices whose item code matches no catalog part.",
        """MATCH (s:SpecialNet) WHERE NOT EXISTS { (s)-[:NET_PRICE_FOR]->() }
           WITH s ORDER BY s.itemCode
           WITH s.vendor AS vendor, count(s) AS nets, collect(s.itemCode)[..20] AS codes
           OPTIONAL MATCH (v:Vendor {key: vendor})
           RETURN vendor AS instance, nets AS count, [{label: 'Vendor', key: vendor}] AS subjects,
                  {vendor: coalesce(v.name, vendor), itemCodes: codes} AS details""",
        lambda d, n: f"{n} {d['vendor']} special nets match no catalog part.",
    ),
    Check(
        "retired_part_still_used", "low",
        "A part no longer in the catalog that approved bids were priced against.",
        """MATCH (c:CatalogItem {retired: true})<-[p:PRICED_AS]-()
           OPTIONAL MATCH (b:Bid {key: p.bid})
           WITH c, p, b ORDER BY b.code
           WITH c, count(p) AS uses, collect(DISTINCT b.code)[..10] AS bids
           RETURN c.key AS instance, uses AS count, [{label: 'CatalogItem', key: c.key}] AS subjects,
                  {part: c.part, vendor: c.vendor, bids: bids} AS details""",
        lambda d, n: (f"{d['vendor']} {d['part']} left the catalog, but {n} approved bid line(s) were "
                      f"priced against it ({', '.join(map(str, d['bids']))})."),
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _record(check: Check, row: dict[str, Any], run: str) -> None:
    key = f"{check.key}:{row['instance']}"
    await graph.write(
        """MERGE (f:Finding {key: $key})
           ON CREATE SET f.firstSeen = $run, f.status = 'open'
           WITH f, f.status = 'resolved' AS reopened
           SET f.check = $check, f.severity = $severity, f.meaning = $meaning, f.summary = $summary,
               f.count = $count, f.details = $details, f.lastSeen = $run,
               f.status = CASE WHEN reopened THEN 'open' ELSE f.status END,
               f.resolvedAt = CASE WHEN reopened THEN null ELSE f.resolvedAt END
           WITH f OPTIONAL MATCH (f)-[old:ABOUT]->() DELETE old""",
        key=key, run=run, check=check.key, severity=check.severity, meaning=check.meaning,
        summary=check.summary(row["details"], int(row["count"])), count=int(row["count"]),
        details=json.dumps(row["details"], default=str, sort_keys=True),
    )
    by_label: dict[str, list[Any]] = defaultdict(list)
    for subject in row["subjects"]:
        if subject["label"] in graph.LABELS:
            by_label[subject["label"]].append(subject["key"])
    for label, keys in by_label.items():
        await graph.write(
            f"MATCH (f:Finding {{key: $key}}) UNWIND $keys AS k MATCH (n:{label} {{key: k}}) MERGE (f)-[:ABOUT]->(n)",
            key=key, keys=keys,
        )


async def _explain(budget: int) -> int:
    """Have the model word the findings whose facts it has not explained yet."""
    pending = await graph.read(
        f"""MATCH (f:Finding {{status: 'open'}})
            WHERE f.explainedFor IS NULL OR f.explainedFor <> f.details
            RETURN f.key AS key, f.check AS check, f.severity AS severity, f.meaning AS meaning,
                   f.summary AS summary, f.details AS details
            ORDER BY {SEVERITY_ORDER}, f.count DESC LIMIT $budget""",
        budget=budget,
    )
    explained = 0
    for finding in pending:
        prompt = (f"Check: {finding['check']} - {finding['meaning']}\n"
                  f"Severity: {finding['severity']}\n"
                  f"Finding: {finding['summary']}\n"
                  f"Facts (JSON): {finding['details']}")
        try:
            asked = await ops_ai.ask(EXPLAIN_FINDING, prompt)
        except Exception as exc:  # no provider is not a failed review: the findings stand
            asked = None
            log.warning("steward could not ask about %s: %s", finding["key"], exc)
        if asked is None or asked.answer is None:
            break  # the provider is down or will not answer; the next run tries again
        answer = asked.answer
        await graph.write(
            """MATCH (f:Finding {key: $key})
               SET f.headline = $headline, f.whyItMatters = $why, f.suggestedFix = $fix,
                   f.whoFixes = $who, f.explainedFor = f.details, f.explainedAt = $at, f.explainedBy = $by""",
            key=finding["key"], headline=answer.headline, why=answer.why_it_matters,
            fix=answer.suggested_fix, who=answer.who_fixes, at=_now(),
            by=f"{EXPLAIN_FINDING.name}@v{EXPLAIN_FINDING.version}",
        )
        explained += 1
    return explained


async def review(*, budget: int = AI_BUDGET) -> dict[str, int]:
    """Run every check, keep the findings current, explain the new ones."""
    run = _now()
    review_days = (await freshness.load()).catalog_stale_days
    params = {"reviewDays": review_days, "isoDate": _ISO_DATE,
              "cutoff": (date.today() - timedelta(days=review_days)).isoformat()}
    seen = 0
    for check in CHECKS:
        for row in await graph.read(check.query, **params):
            await _record(check, row, run)
            seen += 1
    # What the checks no longer see was fixed at its source.
    [resolved] = await graph.write(
        """OPTIONAL MATCH (f:Finding) WHERE f.status IN ['open', 'dismissed'] AND f.lastSeen <> $run
           SET f.status = 'resolved', f.resolvedAt = $run RETURN count(f) AS n""",
        run=run,
    )
    explained = await _explain(budget) if budget > 0 else 0
    [still_open] = await graph.read("MATCH (f:Finding {status: 'open'}) RETURN count(f) AS n")
    await graph.write(
        "MERGE (m:Meta {key: 'steward'}) SET m.lastRunAt = $run, m.open = $open, m.explained = $explained",
        run=run, open=still_open["n"], explained=explained,
    )
    return {"seen": seen, "open": still_open["n"], "resolved": resolved["n"], "explained": explained}


async def dismiss(key: str, *, by: str, note: str | None = None) -> bool:
    """An admin's call that a finding is not a problem. It stays dismissed while it recurs."""
    rows = await graph.write(
        """MATCH (f:Finding {key: $key})
           SET f.status = 'dismissed', f.dismissedBy = $by, f.dismissedAt = $at, f.dismissNote = $note
           RETURN f.key AS key""",
        key=key, by=by, at=_now(), note=note,
    )
    return bool(rows)
