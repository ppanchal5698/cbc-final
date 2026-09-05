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

from cbc.db import db
from cbc.services import pricing

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
    lines = await db.quote_lines.find({"projectId": project_id}).sort("division", 1).to_list(
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


def reprice(lines: list[dict[str, Any]], state: str | None, freight: float | None) -> dict:
    """Price every line in memory and roll them up. Writes nothing.

    Mutates the dicts it is given so the caller can render them, and reports which
    of them actually changed so a persisting caller writes only those.
    """
    changed: list[dict[str, Any]] = []
    for line in lines:
        priced = pricing.price_line(
            cost=line.get("cost"),
            margin=line.get("margin"),
            qty=line.get("qty", 1),
            division=line.get("division"),
        )
        stale = ("sell" not in line) or ("extended" not in line)
        differs = (line.get("sell"), line.get("extended"), line.get("margin")) != (
            priced["sell"],
            priced["extended"],
            priced["margin"],
        )
        line["sell"] = priced["sell"]
        line["extended"] = priced["extended"]
        line["margin"] = priced["margin"]
        # Why a line came back unpriced, so it reads as "needs a look" on the
        # screen rather than just being blank.
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

    quote = await db.quotes.find_one({"projectId": project["_id"]}) or {}
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
    quote = await db.quotes.find_one({"projectId": project_id}) or {}
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
                    }
                },
            )
            for line in result["changed"]
        ]
        await db.quote_lines.bulk_write(operations, ordered=False)

    totals = result["totals"]
    await db.quotes.update_one(
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
