"""Read-only P21 last-PO lookup, in Python (cost path 1).

READ-ONLY by construction: the one HTTP helper hardcodes ``method="GET"`` and has
no body parameter in its signature, so there is no code path that can write - the
same refusal-by-shape ``pageindex/reader.py`` makes, and the guarantee NFR-5 /
``.claude/rules/p21-read-only.md`` require. ``__all__`` pins the public surface to
``last_po`` alone, so a test fails if a write verb is ever added.

P21 is not integrated yet (NR-10). Until ``P21_BASE_URL`` is set, ``last_po``
returns None and the caller falls to the next rung; it never invents a price.

Cache per pass, never at module scope. The worker is a long-lived process
(``WORKER_CLAIM_ALL=1``), so a ``functools.lru_cache`` on a module-level lookup
would persist across bids and leak one customer's PO price into another's quote -
and make ``priced_at`` and the freshness band a lie, the precise failure NFR-3
exists to prevent. The unit is a ``P21Client`` instance constructed inside a pass,
holding its lookup dict and circuit-breaker flag as instance attributes; scope is
structural rather than disciplined.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

__all__ = ["last_po"]


def _base_url() -> str:
    return os.environ.get("P21_BASE_URL", "").strip()


def _get(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """The one network call. ``method="GET"`` is hardcoded and there is no body
    parameter, so no caller can turn this into a write."""
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


class P21Client:
    """Per-pass last-PO cache and circuit breaker. One per ``seed_line_items``."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str | None], dict[str, Any] | None] = {}
        self._down = False  # one failure trips it; no more attempts this pass

    def last_po(self, part_number: str, vendor: str | None = None) -> dict[str, Any] | None:
        """A usable PO -> ``{"cost", "detail", "po_date"}``; an unreliable one ->
        ``{"context"}`` (no cost, estimator context only); stale / future-dated /
        unreachable / unconnected -> ``None`` (the next rung is tried)."""
        base = _base_url()
        if not base or self._down or not str(part_number or "").strip():
            return None
        key = (str(part_number), vendor)
        if key not in self._cache:
            self._cache[key] = self._lookup(base, str(part_number), vendor)
        return self._cache[key]

    def _lookup(self, base: str, part_number: str, vendor: str | None) -> dict[str, Any] | None:
        params = {"part_number": part_number}
        if vendor:
            params["vendor"] = vendor
        url = f"{base.rstrip('/')}/last-po?{urlencode(params)}"
        try:
            payload = _get(url)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
            # Trip the breaker: if P21 is unreachable it is unreachable for the
            # whole pass, and 300 failing lookups help nobody.
            self._down = True
            return None
        if not isinstance(payload, dict):
            return None
        price = payload.get("last_po_price") or payload.get("price") or payload.get("unit_cost")
        po_date = payload.get("po_date") or payload.get("purchase_date") or payload.get("date")
        if price is None or po_date is None:
            return None
        return self._classify(price, str(po_date))

    def _classify(self, price: Any, po_date: str) -> dict[str, Any] | None:
        from cbc.modules.ops.api.freshness import load_sync
        from cbc.modules.ops.api.freshness_rules import classify

        try:
            purchased = datetime.fromisoformat(po_date.replace("Z", "+00:00")).date()
            price_f = float(price)
        except (ValueError, TypeError):
            return None
        age = (date.today() - purchased).days
        bands = load_sync()
        result = classify(
            age,
            bands.fresh_days,
            bands.discard_after_days,
            fresh_months=bands.fresh_months,
            discard_months=bands.discard_after_months,
        )
        status = result["status"]
        if result["usable"]:
            return {"cost": price_f, "detail": f"P21 last PO {po_date} ({status})", "po_date": po_date}
        if status == "unreliable":
            # No cost. The number is estimator context, not a value to quote.
            return {"context": f"P21 last PO {price_f} on {po_date} is unreliable — verify before use"}
        # stale / future_dated: written nowhere.
        return None


def last_po(part_number: str, vendor: str | None = None) -> dict[str, Any] | None:
    """Module-level one-shot: builds a client for a single lookup, for the MCP
    server's use. A pass constructs its own ``P21Client`` and reuses it across
    lines so a bid's lookups share one cache and one breaker."""
    return P21Client().last_po(part_number, vendor)
