"""The match_and_price job: match a bid's take-off to priced rows and price it.

Two engines, chosen in Settings > Pipeline:

- **v2** prices in code. The take-off - openings in Mongo, the legend's sets on
  disk - becomes lines (`domain/takeoff`), and each line is matched and priced by
  the ladder (`domain/ladder`). Where the ladder found one model at several
  prices and the legend's words do not say which, the model is asked to choose
  (`CHOOSE_CATALOG_MATCH`, within a budget); its choice carries its reason and a
  flag to confirm. The result is written to `priced/line_items.json`, which
  review, delivery and the proposal still read, then imported into
  `estimateLines` and rolled up. A line nobody could price is MANUAL with the
  reason - never a failed job.
- **legacy** is the Claude pass: seeded by `preprice`, matched and priced by the
  agents through the catalog MCP server, checked, then synced the same way.

Either way the matching gate (FR-4) then records each opening's rating conflicts
and catalog candidates. It lives in quoting rather than pricing: it writes
quoting's lines and quote, and pricing may not import quoting.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from cbc.modules.catalog.api import products as catalog_products
from cbc.modules.extraction.api import openings as extraction_openings, passes
from cbc.modules.ops.api import ai as ops_ai, jobs as ops_jobs, pipeline as ops_pipeline
from cbc.modules.pricing.api import calc, p21, pricing, reference_library
from cbc.modules.projects.api import bids, pipeline
from cbc.modules.quoting.api import lines as quoting_lines, priced_lines, quote
from cbc.modules.quoting.domain import ladder, matcher, matching, takeoff
from cbc.modules.quoting.domain.questions import CHOOSE_CATALOG_MATCH
from cbc.shared import storage
from cbc.shared.hardware_sets import SET_KEYS
from cbc.shared.pass_files import read_json, write_json

log = logging.getLogger("cbc.worker")

SOURCE = "match_and_price v2 (priced in code)"
CHOICE_BUDGET = 25  # model choices per bid; the rest are the estimator's
# A legend's "supplied by": every party but the GC (whom CBC sells to) furnishes the
# item itself - the landlord, the owner, the storefront supplier, a security vendor.
_IN_SCOPE = {"", "GC", "WIB", "CBC"}
_PARTY_NAMES = {"LL": "landlord", "STOREFRONT": "the storefront supplier"}


async def run(job: dict[str, Any]) -> None:
    if await ops_pipeline.pricing_engine() == "v2":
        await pipeline.run_pass(job, sync=sync_results, work=price_in_code)
        return
    await pipeline.run_pass(job, sync=sync_results, prepare=_prepare, needs_catalog=True)


# ── v2: priced in code ───────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _item(item: dict[str, Any]) -> dict[str, Any]:
    """A legend item in the take-off's terms, whichever reader wrote it."""
    qty = item.get("qty") if item.get("qty") is not None else item.get("quantity")
    if not isinstance(qty, (int, float)) or isinstance(qty, bool):
        # The column reader keeps the count and its unit apart: `1 1/2` and `PR.`.
        qty = " ".join(str(v) for v in (qty, item.get("unit")) if v not in (None, ""))
    specified = item.get("specified") if isinstance(item.get("specified"), dict) else {}
    party = str(item.get("supplied_by") or "").strip().upper()
    others = None if party in _IN_SCOPE else _PARTY_NAMES.get(party, party.lower())
    return {
        "qty": qty,
        "part": item.get("part") or item.get("part_number") or specified.get("part_number"),
        "manufacturer": item.get("manufacturer") or specified.get("manufacturer"),
        "finish": item.get("finish") or specified.get("finish"),
        "description": item.get("description"),
        "notes": item.get("notes"),
        "by_others": others,
        "size": item.get("size") or specified.get("size"),
        "source_page": item.get("source_page"),
    }


def _hardware_sets(slug: str) -> list[dict[str, Any]]:
    payload = read_json(storage.project_dir(slug) / "extracted" / "hardware_sets.json")
    rows = next((payload[k] for k in SET_KEYS if isinstance(payload, dict) and isinstance(payload.get(k), list)), [])
    return [
        {
            "name": row.get("set_id") or row.get("hardware_set") or row.get("name"),
            "items": [_item(item) for item in row.get("items") or [] if isinstance(item, dict)],
            "source_page": row.get("source_page"),
            "source_file": row.get("source_file"),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _takeoff_rows(
    openings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The in-scope openings that cite a hardware set, the specialty rows, and every
    in-scope door with what its door and frame lines are priced from."""
    hardware: list[dict[str, Any]] = []
    specialties: list[dict[str, Any]] = []
    doors: list[dict[str, Any]] = []
    for row in openings:
        # A row superseded by a later pass is kept as `duplicate`; it is not the bid.
        if row.get("inScope") is False or row.get("status") == "duplicate":
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        # The bid alternate the estimator put the row in: priced as its own lines (FR-14).
        where = {"source_page": evidence.get("sourcePage"), "source_file": evidence.get("sourceFile"),
                 "alternate_group": row.get("alternateGroup") or None}
        specialty = row.get("specialty") if isinstance(row.get("specialty"), dict) else None
        if specialty:
            frp = specialty.get("kind") == "frp"
            specialties.append({
                "division": row.get("division") or ("06 64" if frp else "10 28"),
                "qty": row.get("qty"),
                "part": specialty.get("specifiedModel") or (None if frp else row.get("mark")),
                "manufacturer": row.get("manufacturer"),
                "finish": row.get("finish"),
                "description": row.get("description") or specialty.get("productType"),
                "notes": row.get("notes"),
                "room": specialty.get("room") or row.get("location"),
                "unit": specialty.get("unit"),
                "mark": row.get("mark"),
                # What an FRP area measured: perimeter, wall height, corners (FR-12).
                "geometry": {key: specialty.get(key) for key in
                             ("perimeterLf", "wallHeightFt", "insideCorners", "outsideCorners")} if frp else None,
                **where,
            })
            continue
        mark = row.get("mark") or row.get("doorNumber")
        if row.get("hwSet"):
            hardware.append({"mark": mark, "set": row["hwSet"], "count": row.get("qty"),
                             "rating": row.get("fireRating"), **where})
        doors.append({
            "mark": mark, "count": row.get("qty"), "rating": row.get("fireRating"),
            "door_material": row.get("doorMaterial"), "frame_material": row.get("frameMaterial"),
            "door_type": row.get("doorType"), "frame_type": row.get("frameType"),
            "width": row.get("width"), "height": row.get("height"), "frame_depth": row.get("frameDepth"),
            "undecided": row.get("inScope") is None, **where,
        })
    return hardware, specialties, doors


def _tiers(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ladder.vendor_key(v.get("key") or v.get("name")): v for v in payload.get("vendors") or []}


async def _sources(project: dict[str, Any], lines: list[takeoff.Line]) -> ladder.Sources:
    """Every row the ladder may price from, fetched once for the bid."""
    vendors = await catalog_products.vendor_names()

    def models(part: str) -> list[str]:
        return catalog_products.part_candidates(part, vendors)

    wanted: set[str] = set()
    for line in lines:
        for part in (line.part, ladder.guess_part(line)):
            if part:
                wanted.update(m for model in models(part) for m in (model, model.upper()))
    exact = [row for rows in (await catalog_products.by_parts(wanted, quotable=True)).values() for row in rows]
    catalog = list({row["_id"]: row for row in [*exact, *await catalog_products.by_series(wanted)]}.values())
    book = [row for rows in (await catalog_products.list_prices(wanted)).values() for row in rows]
    books = {
        str(b["_id"]): {"name": b.get("program") or b.get("filename"), "effective": b.get("effective")}
        for b in await catalog_products.price_book_summaries()
    }
    nets, tiers, adders = await asyncio.to_thread(
        lambda: (reference_library.load_special_nets(), reference_library.load_vendor_tiers(),
                 reference_library.load_adders()))
    special = await asyncio.to_thread(pricing.special_margin, project.get("gc"), project.get("brand"))
    # A Division 10 part CBC cannot price may have a direct equal it can.
    equals = (await asyncio.to_thread(reference_library.load_div10_equals)
              if any(line.division.startswith("10") for line in lines) else {})
    equal_rows = (await catalog_products.by_vendors(ladder.vendor_key(b) for b in equals.get("preferred_brands") or [])
                  if equals else [])
    client = p21.P21Client()
    return ladder.Sources(
        models=models,
        finish=lambda text: matcher.finish_key(text, reference_library.resolve_finish),
        lapsed=reference_library.sheet_lapsed,
        cost_from_list=lambda price, multiplier: calc.cost_from_list(price, multiplier)["cost"],
        multiplier_category=pricing.multiplier_category,
        special_nets=[row for row in nets.get("items") or [] if isinstance(row, dict)],
        special_net_effective=nets.get("effective_date"),
        catalog=catalog,
        book=book,
        books=books,
        tiers=_tiers(tiers),
        last_po=client.last_po,
        special_margin=special,
        priced_at=_now(),
        equals=equals,
        equal_rows=equal_rows,
        adders=[a for a in (adders.get("hager_list_adders") or {}).get("items") or [] if isinstance(a, dict)],
    )


def plan(project: dict[str, Any], openings: list[dict[str, Any]],
         frp_constants: dict[str, Any] | None = None) -> tuple[list[takeoff.Line], list[str]]:
    """The bid's take-off as lines to price, and what was left out. Reads files only."""
    hardware, specialties, doors = _takeoff_rows(openings)
    lines, notes = takeoff.hardware_lines(_hardware_sets(project["slug"]), hardware)
    return (takeoff.door_and_frame_lines(doors) + lines + takeoff.specialty_lines(specialties, frp_constants),
            notes)


def _choice_prompt(row: dict[str, Any], pending: dict[str, Any]) -> str:
    said = " ".join(str(row.get(k)) for k in ("manufacturer", "part_number", "description", "finish") if row.get(k))
    listed = "\n".join(f"{n}. {shown}" for n, shown in enumerate(pending["shown"], start=1))
    return f"Specified: {said}\nRows ({pending['rung']}):\n{listed}"


async def _choose(rows: list[dict[str, Any]], sources: ladder.Sources, *, budget: int) -> int:
    """Ask the model to settle the lines the ladder could not, within the budget.

    The first question that goes unanswered ends the asking: the provider is down
    or will not answer, and the rest stay the estimator's to pick.
    """
    chosen = asked = 0
    for index, row in enumerate(rows):
        pending = row.get(ladder.UNDECIDED)
        if not pending or asked >= budget:
            continue
        asked += 1
        try:
            reply = await ops_ai.ask(CHOOSE_CATALOG_MATCH, _choice_prompt(row, pending))
        except Exception as exc:  # no provider is not a failed bid: the lines stay MANUAL
            log.warning("choose_catalog_match not asked: %s", exc)
            break
        if reply.answer is None:
            break
        if reply.answer.choice is None:
            continue
        priced = await asyncio.to_thread(ladder.price_choice, row, reply.answer.choice - 1, reply.answer.reason, sources)
        if priced is not None:
            rows[index] = priced
            chosen += 1
    return chosen


def _stock_lists(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    """The stock list of each door-hardware vendor on the bid that has one (NR-6)."""
    vendors = {ladder.vendor_key(row.get("manufacturer")) for row in rows
               if str(row.get("division") or "").startswith("08 7") and row.get("manufacturer")}
    found = {vendor: reference_library.load_stock_list(vendor) for vendor in vendors if vendor}
    return {vendor: reference_library.stock_parts(payload) for vendor, payload in found.items() if payload}


def _mark_stock(row: dict[str, Any], lists: dict[str, set[str]]) -> None:
    """Whether a hardware part is on its maker's stock list - a part that is not
    is usually a lead time, which the estimator should know before quoting it."""
    parts = lists.get(ladder.vendor_key(row.get("manufacturer")))
    part = str(row.get("part_number") or "").strip()
    if parts is None or not part or not str(row.get("division") or "").startswith("08 7"):
        return
    row["stock"] = reference_library.in_stock(parts, part)
    if not row["stock"]:
        row["flags"].append("non_stock")


async def price_bid(project: dict[str, Any], *, choose: bool = True) -> dict[str, Any]:
    """The priced file for a bid, as v2 would write it. Writes nothing - the
    job writes it; an evaluation compares it with the estimators' own quote."""
    openings = await extraction_openings.list_for_project(project["_id"], limit=5000)
    frp_constants = await asyncio.to_thread(reference_library.load_frp_constants)
    lines, notes = plan(project, openings, frp_constants)
    sources = await _sources(project, lines)
    rows = await asyncio.to_thread(lambda: [row for line in lines for row in ladder.price(line, sources)])
    if choose:
        await _choose(rows, sources, budget=CHOICE_BUDGET)
    stock = await asyncio.to_thread(_stock_lists, rows)
    for row in rows:
        _mark_stock(row, stock)
        if ladder.UNDECIDED in row:
            row["close_matches"] = ladder.close_matches(row, sources)
        row.pop(ladder.UNDECIDED, None)
    priced = sum(1 for row in rows if row.get("cost") is not None)
    return {
        "source": SOURCE,
        "generated_at": sources.priced_at,
        "lines": rows,
        "flags": notes,
        "summary": {"total_lines": len(rows), "lines_with_cost": priced,
                    "manual_cutoff_applied": priced < len(rows)},
    }


async def price_in_code(job: dict[str, Any], project: dict[str, Any]) -> str:
    """The v2 pass: price the take-off, write it where the pass's output goes, sync it."""
    payload = await price_bid(project)
    if not payload["lines"]:
        return "nothing to price: no in-scope opening cites a hardware set and no specialty row was read"
    if not await ops_jobs.holds_lease(job):
        return "lease stolen; discarded output"
    path = storage.project_dir(project["slug"]) / "priced" / "line_items.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(write_json, path, payload)
    return await _sync(job, project, payload)


async def _sync(job: dict[str, Any], project: dict[str, Any], payload: dict[str, Any]) -> str:
    counts = await priced_lines.import_quote_lines(project, job=job)
    if counts.get("aborted"):
        return "lease stolen; discarded output"
    await quote.persist(project)
    await apply_to_project(project)
    await bids.set_stage(project["_id"], "quote", 67)
    summary = payload["summary"]
    note = (f"priced in code: {summary['lines_with_cost']}/{summary['total_lines']} lines have a cost; "
            f"{counts['inserted']} new, {counts['updated']} updated, {counts['skipped']} kept as the estimator left them")
    if summary["total_lines"] and summary["lines_with_cost"] == 0:
        from cbc.modules.projects.api import saga as chain

        await chain.set_state(project["_id"], "pricing",
                              detail="pricing incomplete — all manual; estimator must enter distributor costs")
        note += " (all manual cutoff)"
    return note


# ── legacy: the Claude pass ──────────────────────────────────────────────────


async def _prepare(job: dict[str, Any], project: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Seed priced/line_items.json deterministically before the pass, so the pass
    handles judgment, not arithmetic (W4). PREPRICE_SEED reverts the whole phase -
    the same flag also selects the prompt's cost ladder, read through one helper."""
    from cbc.modules.pricing.api import preprice

    if preprice.preprice_seed_enabled():
        result = await asyncio.to_thread(preprice.seed_line_items, project["slug"])
        if result.get("written"):
            log.info(
                "%s pre-priced %s line(s) before the pass",
                project.get("code", project["slug"]),
                result.get("lines"),
            )
    return True


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    counts = await priced_lines.import_quote_lines(project, job=job)
    if counts.get("aborted"):
        return "lease stolen; discarded output"
    await quote.persist(project)
    await apply_to_project(project)
    await bids.set_stage(project["_id"], "quote", 67)

    from cbc.modules.pricing.api.list_x_backfill import priced_line_metrics
    from cbc.modules.projects.api import saga as chain

    metrics = priced_line_metrics(project["slug"])
    total = metrics["total_lines"]
    with_cost = metrics["lines_with_cost"]
    pricing_note = (
        f"{counts['inserted']} priced, {counts['updated']} updated, "
        f"{counts['skipped']} kept; {with_cost}/{total} lines have cost"
    )
    if total and with_cost == 0:
        await chain.set_state(
            project["_id"],
            "pricing",
            detail="pricing incomplete — all manual; estimator must enter distributor costs",
        )
        pricing_note += " (all manual cutoff)"
    return pricing_note


# ── the matching gate (FR-4) ─────────────────────────────────────────────────


async def apply_to_project(project: dict[str, Any], *, limit: int = 5000) -> dict[str, int]:
    """Judge each opening against the catalog rows of the parts its lines name.

    A line names the doors it is for (`openings`); an opening's candidates are
    the catalog rows for the parts on its lines. An opening with no fire rating to
    enforce is flagged ratingMissing.
    """
    project_id = project["_id"]
    openings = await extraction_openings.list_for_project(project_id, limit=limit)
    parts_for: dict[str, list[str]] = {}
    for line in await quoting_lines.list_for_project(project_id):
        part = line.get("part") or line.get("partNumber")
        for mark in line.get("openings") or []:
            if part:
                parts_for.setdefault(str(mark), []).append(part)

    def mark_of(opening: dict[str, Any]) -> str:
        return str(opening.get("mark") or opening.get("doorNumber") or "")

    # One catalog query and one bulk write for the bid. This was a query and an
    # update per opening - two round trips a door, a thousand on a 500-door bid.
    catalog = await catalog_products.by_parts(p for o in openings for p in parts_for.get(mark_of(o), []))
    flagged = 0
    updates: list[tuple[Any, dict[str, Any]]] = []
    for opening in openings:
        candidates = [
            {
                "id": str(product.get("_id")),
                "part": product.get("part"),
                "fire_rating": product.get("fireRating") or product.get("rating"),
                "handing": product.get("handing"),
                "finish": product.get("finish"),
                "description": product.get("description"),
            }
            for part in parts_for.get(mark_of(opening), [])
            for product in catalog.get(part, [])
        ]
        opening_view = {
            **opening,
            "fire_rating": opening.get("fire_rating") or opening.get("fireRating"),
        }
        result = matching.candidates(opening_view, candidates)
        updates.append((opening["_id"], {
            "ratingConflict": result["ratingConflict"],
            "ratingMissing": result["ratingMissing"],
            "matchCandidates": result["matchCandidates"],
        }))
        if result["ratingConflict"] or result["ratingMissing"]:
            flagged += 1
    await extraction_openings.update_fields_many(updates)

    return {"openings": len(openings), "flagged": flagged}
