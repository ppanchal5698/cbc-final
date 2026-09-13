"""Re-pricing a quote and rolling it up.

One implementation, called from three places that used to reach into the quote
router for it: the quote screen, the proposal screen, and the worker's sync after
a pricing pass.

The important property is that computing and storing are separate. `GET /quote`
called a function that wrote a row per line and upserted the totals, so two
browser tabs on one bid interleaved their writes, a `PATCH` landing between
another request's read and its write was silently reverted, and the page could
not be cached or safely retried. Reads now compute; only the routes that change
something persist.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from pymongo import UpdateOne

from cbc.modules.quoting.infrastructure.collections import estimate_lines, quotes
from cbc.modules.pricing.api import pricing

log = logging.getLogger("cbc.services.quote")

# Bids above this are refused rather than silently truncated.
MAX_QUOTE_LINES = 10_000

# Short TTL cache so polling during a job does not reprice thousands of lines
# every four seconds on every tab.
_TOTALS_CACHE_TTL = 3.0
_totals_cache: dict[str, tuple[float, dict, list[dict[str, Any]]]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_key(project_id) -> str:
    return str(project_id)


def invalidate_totals_cache(project_id) -> None:
    _totals_cache.pop(_cache_key(project_id), None)


async def lines_for(project_id) -> list[dict[str, Any]]:
    lines = await estimate_lines().find({"projectId": project_id}).sort("division", 1).to_list(
        MAX_QUOTE_LINES + 1
    )
    if len(lines) > MAX_QUOTE_LINES:
        raise ValueError(
            f"this bid has more than {MAX_QUOTE_LINES} quote lines; "
            "contact an administrator before repricing"
        )
    return lines


def tax_state(project: dict[str, Any], quote: dict[str, Any]) -> str | None:
    """Which jurisdiction decides the tax on this bid.

    "NONE" is the estimator saying there is no nexus. Otherwise the ship-to
    state on the project row is authoritative on every reprice - the first
    pricing pass must not freeze a model-written jurisdiction into the quote.
    """
    stored = quote.get("taxJurisdiction")
    if stored == "NONE":
        return "NONE"
    # Honor an explicit settings override (e.g. OH nexus on a NY ship-to bid).
    # Auto-persisted jurisdiction always matches project.state and must not
    # block ship-to from staying authoritative on every reprice.
    if stored and stored != project.get("state"):
        return stored
    return project.get("state")


def _resolve_margin(line: dict[str, Any]) -> tuple[float | None, dict[str, Any] | None]:
    """The margin to price at, and the snapshot that records where it came from.

    §4.8: the snapshots "are not caches and must never be refreshed". Before this,
    a line with no explicit margin re-derived one from the *current* bands on
    every reprice, so editing the framework silently repriced quotes that had
    already been sent.

    Telling an estimator's override from our own output is the reason the old code
    re-derived at all: `reprice` writes the applied margin back onto `line`, so on
    the next pass it cannot tell 0.27-because-the-band-said-so from
    0.27-because-a-person-typed-it. The frozen rate settles it - a `margin` that
    differs from the snapshot is a person changing their mind, and anything equal
    to it is our own echo.
    """
    cost = line.get("cost")
    margin = line.get("margin")
    snapshot = line.get("marginSnapshot")

    # An unpriced line - MANUAL, or awaiting a vendor quote - has no price for a
    # snapshot to make traceable. Freezing a margin here would invent one.
    if cost is None:
        return margin, None

    band = pricing.band_for_division(line.get("division"))

    if snapshot and (margin is None or margin == snapshot.get("rate")):
        return snapshot.get("rate"), snapshot  # frozen, unchanged

    if margin is not None:
        applied, resolved_from, overridden = float(margin), "override", True
    else:
        applied, resolved_from, overridden = pricing.default_margin(line.get("division")), "band", False

    return applied, {
        "band": band,
        "rate": applied,
        "overridden": overridden,
        "resolvedFrom": resolved_from,
        "frozenAt": datetime.now(timezone.utc),
    }


def _freeze_snapshot(existing: dict[str, Any] | None, built: dict[str, Any] | None) -> dict[str, Any] | None:
    """§4.8: once frozen, a snapshot is never refreshed from live reference data."""
    if existing:
        return existing
    return built


def _cost_snapshot(line: dict[str, Any]) -> dict[str, Any] | None:
    """Freeze the cost that was priced - refresh only when the line's cost changes.

    An estimator PATCH that changes `cost` is a new decision and must replace the
    snapshot. What §4.8 forbids is a *reference* edit (price book, P21 refresh)
    silently moving a quoted line; that path does not write `line.cost`.
    """
    cost = line.get("cost")
    if cost is None:
        return None
    existing = line.get("costSnapshot")
    if existing is not None and existing.get("cost") == cost:
        return existing
    return {
        "cost": cost,
        "costSource": line.get("costSource"),
        "costSourceDetail": line.get("costSourceDetail"),
        "frozenAt": datetime.now(timezone.utc),
    }


def _price_book_snapshot(line: dict[str, Any]) -> dict[str, Any] | None:
    existing = line.get("priceBookSnapshot")
    if existing:
        return existing  # frozen - reference edits must not move it
    if not any(line.get(k) for k in ("listPrice", "priceBookId", "priceBookPage", "vendor")):
        return None
    return {
        "listPrice": line.get("listPrice"),
        "priceBookId": line.get("priceBookId"),
        "priceBookPage": line.get("priceBookPage"),
        "vendor": line.get("vendor") or line.get("manufacturer"),
        "frozenAt": datetime.now(timezone.utc),
    }


def _multiplier_tier_snapshot(line: dict[str, Any]) -> dict[str, Any] | None:
    existing = line.get("multiplierTierSnapshot")
    if existing:
        return existing
    if line.get("multiplier") is None and not line.get("multiplierTier"):
        return None
    return {
        "multiplier": line.get("multiplier"),
        "tier": line.get("multiplierTier") or line.get("tier"),
        "program": line.get("program"),
        "frozenAt": datetime.now(timezone.utc),
    }


def reprice(lines: list[dict[str, Any]], state: str | None, freight: float | None) -> dict:
    """Price every line in memory and roll them up. Writes nothing.

    Mutates the dicts it is given so the caller can render them, and reports which
    of them actually changed so a persisting caller writes only those.
    """
    changed: list[dict[str, Any]] = []
    for line in lines:
        applied, snapshot = _resolve_margin(line)
        priced = pricing.price_line(
            cost=line.get("cost"),
            margin=applied,
            qty=line.get("qty", 1),
            division=line.get("division"),
        )
        if snapshot is not None:
            line["marginSnapshot"] = snapshot
        cost_snap = _cost_snapshot(line)
        if cost_snap is not None:
            line["costSnapshot"] = cost_snap
        pb_snap = _price_book_snapshot(line)
        if pb_snap is not None:
            line["priceBookSnapshot"] = pb_snap
        tier_snap = _multiplier_tier_snapshot(line)
        if tier_snap is not None:
            line["multiplierTierSnapshot"] = tier_snap
        stale = ("sell" not in line) or ("extended" not in line)
        differs = (line.get("sell"), line.get("extended"), line.get("margin")) != (
            priced["sell"],
            priced["extended"],
            priced["margin"],
        )
        line["sell"] = priced["sell"]
        line["extended"] = priced["extended"]
        line["margin"] = priced["margin"]
        line["priceError"] = priced.get("error")
        line["marginCheck"] = pricing.check_margin(line.get("division"), priced["margin"])
        if stale or differs or line.get("priceError") != priced.get("error"):
            changed.append(line)

    return {"totals": pricing.totals(lines, state, freight), "changed": changed}


async def totals_for(
    project: dict[str, Any], *, use_cache: bool = True
) -> tuple[dict, list[dict[str, Any]]]:
    """Current totals and priced lines, without touching the database."""
    key = _cache_key(project["_id"])
    if use_cache:
        cached = _totals_cache.get(key)
        if cached and time.monotonic() - cached[0] < _TOTALS_CACHE_TTL:
            return cached[1], cached[2]

    quote = await quotes().find_one({"projectId": project["_id"]}) or {}
    lines = await lines_for(project["_id"])
    result = reprice(lines, tax_state(project, quote), quote.get("freight"))
    totals = result["totals"]
    if use_cache:
        _totals_cache[key] = (time.monotonic(), totals, lines)
    return totals, lines


async def persist(project: dict[str, Any]) -> dict:
    """Re-price, store the results, and return the totals.

    Called from the routes that change something and from the worker once a
    pricing pass has landed - never from a read.
    """
    invalidate_totals_cache(project["_id"])
    project_id = project["_id"]
    quote = await quotes().find_one({"projectId": project_id}) or {}
    state = tax_state(project, quote)

    lines = await lines_for(project_id)
    result = reprice(lines, state, quote.get("freight"))

    if result["changed"]:
        operations = [
            UpdateOne(
                {"_id": line["_id"]},
                {
                    "$set": {
                        "sell": line["sell"],
                        "extended": line["extended"],
                        "margin": line["margin"],
                        "priceError": line["priceError"],
                        "marginCheck": line["marginCheck"],
                        "marginSnapshot": line.get("marginSnapshot"),
                        "costSnapshot": line.get("costSnapshot"),
                        "priceBookSnapshot": line.get("priceBookSnapshot"),
                        "multiplierTierSnapshot": line.get("multiplierTierSnapshot"),
                    }
                },
            )
            for line in result["changed"]
        ]
        await estimate_lines().bulk_write(operations, ordered=False)

    totals = result["totals"]
    await quotes().update_one(
        {"projectId": project_id},
        {
            "$set": {
                **totals,
                "updatedAt": _now(),
                "quoteNumber": quote.get("quoteNumber") or f"Q-{project.get('code', '')}",
            },
            "$setOnInsert": {"projectId": project_id, "createdAt": _now()},
        },
        upsert=True,
    )
    return totals


async def quote_document(project_id: Any) -> dict[str, Any]:
    """The stored quote - settings and last persisted totals - or an empty one."""
    return await quotes().find_one({"projectId": project_id}) or {}


async def by_project(ids: list[Any]) -> dict[Any, dict[str, Any]]:
    """The stored quote for each of these bids, keyed by bid id, for the board."""
    return {
        quote["projectId"]: quote
        for quote in await quotes().find({"projectId": {"$in": ids}}).to_list(len(ids) + 1)
    }
