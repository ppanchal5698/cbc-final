#!/usr/bin/env python3
"""p21-connector MCP server - READ-ONLY last-PO cost lookup.

Cost path 1 of three (.claude/memory/cost_sourcing_rules.md).

There are no write tools in this module. That is the guardrail, not an oversight
(NFR-5, .claude/rules/p21-read-only.md).

P21 is not integrated yet (NR-10 - feasibility under investigation). Until
P21_BASE_URL is set, every lookup returns a structured "manual entry required"
response with a refresh prompt. It never invents a price.
"""
from __future__ import annotations

import json
import os
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from _runtime import serve
from tools import TOOLS
from client import lookup_last_po as _http_lookup, search_item as _http_search
from cbc.domain.freshness import classify
from cbc.services.freshness import load_sync

BASE_URL = os.environ.get("P21_BASE_URL", "").strip()

MANUAL_ENTRY = {
    "connected": False,
    "cost": None,
    "cost_source": "MANUAL",
    "action_required": "manual_price_entry",
    "prompt": "price may be out of date - refresh",
    "reason": (
        "P21 is not connected in this environment. Integration feasibility and a "
        "part-number / semi-item matching strategy are still open (NR-10)."
    ),
    "fallbacks": [
        "Path 2: vendor list price x multiplier tier (pricebook MCP server)",
        "Path 3: distributor lookup (Banner Solutions, SecLock, J2) or vendor RFQ",
    ],
}


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def check_freshness(po_date: str) -> dict[str, Any]:
    try:
        purchased = _parse_date(po_date)
    except ValueError as exc:
        raise ValueError(f"po_date must be an ISO date, got {po_date!r}") from exc

    age = (date.today() - purchased).days
    bands = load_sync()
    classified = classify(
        age,
        bands.fresh_days,
        bands.discard_after_days,
        fresh_months=bands.fresh_months,
        discard_months=bands.discard_after_months,
    )

    return {
        "po_date": po_date,
        "age_days": age,
        "freshness_status": classified["status"],
        "usable": classified["usable"],
        "guidance": classified["guidance"],
        "rule": bands.rule,
    }


def lookup_last_po(part_number: str, vendor: str | None = None) -> dict[str, Any]:
    if not BASE_URL:
        return {
            "part_number": part_number,
            "vendor": vendor,
            "last_po_price": None,
            "po_date": None,
            "freshness_status": "unknown",
            "item_id": None,
            **MANUAL_ENTRY,
        }

    try:
        payload = _http_lookup(part_number, vendor)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {
            "part_number": part_number,
            "vendor": vendor,
            "connected": True,
            "error": f"P21 lookup failed: {exc}",
            **MANUAL_ENTRY,
        }

    price = payload.get("last_po_price") or payload.get("price") or payload.get("unit_cost")
    po_date = payload.get("po_date") or payload.get("purchase_date") or payload.get("date")
    item_id = payload.get("item_id") or payload.get("id")

    if price is None or po_date is None:
        return {
            "part_number": part_number,
            "vendor": vendor,
            "connected": True,
            "item_id": item_id,
            "last_po_price": price,
            "po_date": po_date,
            "freshness_status": "unknown",
            "error": "P21 response missing price or PO date — use manual entry.",
            **MANUAL_ENTRY,
        }

    freshness = check_freshness(str(po_date))
    return {
        "part_number": part_number,
        "vendor": vendor,
        "connected": True,
        "item_id": item_id,
        "last_po_price": price,
        "po_date": po_date,
        "cost": price,
        "cost_source": "P21_LAST_PO",
        "freshness_status": freshness["freshness_status"],
        "freshness": freshness,
        "action_required": None if freshness["usable"] else "manual_price_entry",
        "prompt": None if freshness["usable"] else "price may be out of date - refresh",
    }


def search_item(query: str, limit: int = 10) -> dict[str, Any]:
    if not BASE_URL:
        return {
            "query": query,
            "limit": limit,
            "connected": False,
            "results": [],
            "known_risks": [
                "P21 item IDs frequently differ from manufacturer part numbers.",
                "Semi-custom items will not match at all.",
                "Manual cost entry must always remain available.",
            ],
            "note": MANUAL_ENTRY["reason"],
        }

    try:
        payload = _http_search(query, limit)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {
            "query": query,
            "limit": limit,
            "connected": True,
            "results": [],
            "error": f"P21 search failed: {exc}",
            "known_risks": [
                "P21 item IDs frequently differ from manufacturer part numbers.",
                "Semi-custom items will not match at all.",
                "Manual cost entry must always remain available.",
            ],
        }

    raw = payload.get("results") or payload.get("items") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    results = []
    for row in raw[:limit]:
        if not isinstance(row, dict):
            continue
        results.append(
            {
                "item_id": row.get("item_id") or row.get("id"),
                "part_number": row.get("part_number") or row.get("sku") or row.get("description"),
                "description": row.get("description") or row.get("name"),
                "vendor": row.get("vendor"),
            }
        )
    return {
        "query": query,
        "limit": limit,
        "connected": True,
        "results": results,
        "known_risks": [
            "P21 item IDs frequently differ from manufacturer part numbers.",
            "Semi-custom items will not match at all.",
            "Manual cost entry must always remain available.",
        ],
    }


HANDLERS = {
    "lookup_last_po": lookup_last_po,
    "check_freshness": check_freshness,
    "search_item": search_item,
}

# Guardrail: assert at import time that nothing mutating ever creeps in.
_FORBIDDEN = ("write", "update", "insert", "post", "create", "delete", "set_")
assert not [t for t in TOOLS if any(word in t["name"].lower() for word in _FORBIDDEN)], (
    "p21-connector must expose no write tools (NFR-5)"
)


def _demo() -> None:
    """Runnable check: the freshness bands and the never-guess contract."""
    assert check_freshness(date.today().isoformat())["freshness_status"] == "fresh"
    mid = (date.today() - timedelta(days=800)).isoformat()
    assert check_freshness(mid)["freshness_status"] == "unreliable"
    ancient = (date.today() - timedelta(days=1000)).isoformat()
    assert check_freshness(ancient)["freshness_status"] == "stale"

    result = lookup_last_po("3510", "hager")
    assert result["last_po_price"] is None and result["cost_source"] == "MANUAL"
    print("p21-connector demo OK -", json.dumps(result["prompt"]))


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        serve("p21-connector", TOOLS, HANDLERS)
