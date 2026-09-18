"""Fill null-cost lines from the product catalog (catalogItems) before PDF Path 2.

Runs after the pricing agent. Prefer curated catalog.md / hand-added rows via
`lookup_catalog_item`. Allegion / distributor MANUAL lines are left alone.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from cbc.modules.pricing.domain import calc as quote_calc
from cbc.shared import storage
from cbc.shared.pass_files import read_json, write_json

# The catalog lookup is a *port*, not an import.
#
# pricing already imports catalog nowhere else, while catalog imports pricing in
# five places (margins, confidence floor, vendor tiers). Importing
# `catalog.api.pageindex.reader` here closed that into a cycle, which
# `tests/architecture/test_layering.py` forbids and which makes either module
# impossible to load on its own. The composition root binds the real reader the
# same way `projects.api.board_sources` takes its opening counts from extraction.
_lookup_catalog_item: Callable[[str, str | None], dict[str, Any] | None] | None = None


class CatalogUnavailable(RuntimeError):
    """No catalog lookup is bound, or the one bound cannot reach its data."""


def bind_catalog_lookup(lookup: Callable[[str, str | None], dict[str, Any] | None]) -> None:
    """Catalog supplies the part lookup when it registers."""
    global _lookup_catalog_item
    _lookup_catalog_item = lookup


def _catalog_row(part: str, vendor: str | None) -> dict[str, Any] | None:
    if _lookup_catalog_item is None:
        raise CatalogUnavailable("no catalog lookup bound; catalog binds it when it registers")
    return _lookup_catalog_item(part, vendor)

_PART = re.compile(r"[A-Z0-9]+", re.I)

_ALLEGIION = ("von duprin", "lcn", "schlage", "ives", "allegion")
_SKIP_SOURCES = {
    "DISTRIBUTOR_MANUAL",
    "VENDOR_RFQ",
    "P21_LAST_PO",
    "SPECIAL_NET",
    "CATALOG_BASELINE",
    "LIST_X_MULTIPLIER",
}


def _norm_part(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _collect_items(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        items = node.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    out.append(item)
                    _collect_items(item, out)
        for key in ("hardware_sets", "openings", "groups"):
            child = node.get(key)
            if isinstance(child, list):
                for row in child:
                    _collect_items(row, out)
            elif isinstance(child, dict):
                _collect_items(child, out)
    elif isinstance(node, list):
        for row in node:
            _collect_items(row, out)


def _hardware_items(slug: str) -> list[dict[str, Any]]:
    payload = read_json(storage.project_dir(slug) / "extracted" / "hardware_sets.json")
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    _collect_items(payload, out)
    return out


def _item_part(item: dict[str, Any]) -> str:
    matched = item.get("matched") if isinstance(item.get("matched"), dict) else {}
    specified = item.get("specified")
    spec_part = specified.get("part_number") if isinstance(specified, dict) else None
    for candidate in (
        item.get("part_number"),
        item.get("part"),
        matched.get("part_number") if isinstance(matched, dict) else None,
        spec_part,
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _index_hardware(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for item in items:
        raw = _item_part(item)
        if not raw:
            continue
        keyed.setdefault(_norm_part(raw), item)
        for token in _PART.findall(raw):
            if len(token) >= 3:
                keyed.setdefault(token.upper(), item)
    return keyed


def _is_allegion(line: dict[str, Any], hw: dict[str, Any] | None) -> bool:
    source = str(line.get("cost_source") or (hw or {}).get("cost_source") or "").upper()
    if source == "DISTRIBUTOR_MANUAL":
        return True
    blob = " ".join(
        str(x or "")
        for x in (
            line.get("manufacturer"),
            line.get("vendor"),
            line.get("description"),
            line.get("part_number"),
            (hw or {}).get("manufacturer"),
            (hw or {}).get("part_number"),
            (hw or {}).get("matched", {}).get("manufacturer")
            if isinstance((hw or {}).get("matched"), dict)
            else None,
            (hw or {}).get("specified", {}).get("manufacturer")
            if isinstance((hw or {}).get("specified"), dict)
            else None,
        )
    ).lower()
    return any(token in blob for token in _ALLEGIION)


def _should_backfill(line: dict[str, Any], hw: dict[str, Any] | None) -> bool:
    if line.get("cost") is not None:
        return False
    source = str(line.get("cost_source") or "").upper()
    if source in _SKIP_SOURCES:
        return False
    if _is_allegion(line, hw):
        return False
    return True


def _resolve_part(line: dict[str, Any], hw: dict[str, Any] | None) -> str:
    for candidate in (
        _item_part(hw) if hw else "",
        line.get("part_number"),
        line.get("part"),
        line.get("model"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _default_margin(row: dict[str, Any], line: dict[str, Any]) -> float:
    raw = line.get("margin")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    dm = row.get("defaultMargin")
    if dm is not None:
        try:
            return float(dm)
        except (TypeError, ValueError):
            pass
    division = str(row.get("division") or line.get("division") or "")
    vendor = str(row.get("vendorKey") or "").lower()
    if division.startswith("10 28") or vendor in {
        "bobrick",
        "gamco",
        "asi",
        "bradley",
        "world_dryer",
    }:
        return 0.56
    return 0.27


def _apply_catalog(line: dict[str, Any], row: dict[str, Any]) -> bool:
    cost = row.get("cost")
    if cost is None:
        list_price = row.get("listPrice")
        mult = row.get("multiplier")
        if list_price is not None and mult is not None:
            try:
                cost = round(float(list_price) * float(mult), 2)
            except (TypeError, ValueError):
                return False
        else:
            return False
    try:
        cost_f = float(cost)
    except (TypeError, ValueError):
        return False
    if cost_f < 0:
        return False

    qty = float(line.get("quantity") or 1)
    margin = _default_margin(row, line)
    priced = quote_calc.calculate_line(cost=cost_f, margin=margin, quantity=qty)
    seed = row.get("seedSource") or "product catalog"
    part = row.get("part") or line.get("part_number")
    line["cost"] = priced["cost"]
    line["sale_ea"] = priced["sale_ea"]
    line["ext_price"] = priced["ext_price"]
    line["margin"] = margin
    line["cost_source"] = "CATALOG_BASELINE"
    line["cost_source_detail"] = f"product catalog / {seed} part {part}"
    if row.get("listPrice") is not None and line.get("list_price") in (None, ""):
        line["list_price"] = row.get("listPrice")
    if row.get("multiplier") is not None and line.get("multiplier") in (None, ""):
        line["multiplier"] = row.get("multiplier")
    flags = list(line.get("flags") or [])
    for drop in ("requires_page_lookup", "manual_page_lookup_pending"):
        if drop in flags:
            flags.remove(drop)
    if "catalog_baseline_backfilled" not in flags:
        flags.append("catalog_baseline_backfilled")
    line["flags"] = flags
    return True


def backfill_priced_lines(slug: str) -> dict[str, int]:
    """Rewrite ``priced/line_items.json`` with catalogItems costs where possible."""
    path = storage.project_dir(slug) / "priced" / "line_items.json"
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {"attempted": 0, "filled": 0, "skipped": 0}

    lines = payload.get("lines") or payload.get("line_items") or []
    if not isinstance(lines, list):
        return {"attempted": 0, "filled": 0, "skipped": 0}

    hw_index = _index_hardware(_hardware_items(slug))
    attempted = filled = skipped = 0
    for line in lines:
        if not isinstance(line, dict):
            continue
        tokens = [t.upper() for t in _PART.findall(str(line.get("part_number") or "")) if len(t) >= 3]
        part_key = _norm_part(line.get("part_number"))
        hw = hw_index.get(part_key)
        for token in reversed(tokens):
            if hw is not None:
                break
            hw = hw_index.get(token)
        if not _should_backfill(line, hw):
            continue
        part = _resolve_part(line, hw)
        if not part:
            continue
        attempted += 1
        vendor = None
        matched = (hw or {}).get("matched") if hw else None
        if isinstance(matched, dict):
            vendor = matched.get("manufacturer") or matched.get("vendor")
        vendor = vendor or line.get("manufacturer") or line.get("vendor")
        try:
            row = _catalog_row(part, vendor)
        except Exception:
            # No catalog, no credential, or a bad row: this backfill is an
            # enhancement, so a miss costs this line and never the quote.
            skipped += 1
            continue
        if row is None or not _apply_catalog(line, row):
            skipped += 1
            continue
        filled += 1

    if filled:
        payload["lines"] = lines
        payload.pop("line_items", None)
        total = len(lines)
        with_cost = sum(
            1
            for row in lines
            if isinstance(row, dict)
            and isinstance(row.get("cost"), (int, float))
            and not isinstance(row.get("cost"), bool)
        )
        payload["summary"] = {
            **(payload.get("summary") if isinstance(payload.get("summary"), dict) else {}),
            "total_lines": total,
            "lines_with_cost": with_cost,
            "catalog_baseline_backfilled": filled,
            "manual_cutoff_applied": with_cost < total,
        }
        write_json(path, payload)
    return {"attempted": attempted, "filled": filled, "skipped": skipped}
