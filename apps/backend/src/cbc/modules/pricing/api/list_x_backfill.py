"""Fill LIST_X multiplier lines the pricing agent left at MANUAL/null cost."""
from __future__ import annotations

import re
from typing import Any

from cbc.modules.pricing.api import hager_list_price
from cbc.modules.pricing.domain import calc as quote_calc
from cbc.shared import storage
from cbc.shared.pass_files import read_json, write_json

_PART = re.compile(r"[A-Z0-9]+", re.I)
_BLOCK_SOURCES = frozenset({"DISTRIBUTOR_MANUAL", "VENDOR_RFQ"})
_ALLEGIION = ("von duprin", "lcn", "schlage", "ives", "allegion")
_THRESH_WEATHER_MULT = 0.4


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


def _item_part(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
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


def _item_type(item: dict[str, Any] | None, line: dict[str, Any]) -> str:
    specified = (item or {}).get("specified")
    spec_desc = specified.get("description") if isinstance(specified, dict) else None
    for candidate in (
        (item or {}).get("item_type"),
        (item or {}).get("category"),
        spec_desc,
        line.get("description"),
        (item or {}).get("description"),
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
            token_u = token.upper()
            if len(token_u) >= 3:
                keyed.setdefault(token_u, item)
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
            (hw or {}).get("specified") if isinstance((hw or {}).get("specified"), str) else None,
        )
    ).lower()
    return any(token in blob for token in _ALLEGIION)


def _should_backfill(line: dict[str, Any], hw: dict[str, Any] | None) -> bool:
    if line.get("cost") is not None:
        return False
    line_source = str(line.get("cost_source") or "").upper()
    hw_source = str((hw or {}).get("cost_source") or "").upper()
    if line_source in _BLOCK_SOURCES or hw_source in _BLOCK_SOURCES:
        return False
    if _is_allegion(line, hw):
        return False
    if hw_source == "LIST_X_MULTIPLIER" or line_source == "LIST_X_MULTIPLIER":
        return True
    part = _item_part(hw) or str(line.get("part_number") or line.get("part") or "")
    item_type = _item_type(hw, line)
    width_in = hager_list_price.parse_width_inches(
        part,
        line.get("part_number"),
        line.get("description"),
        line.get("notes"),
        (hw or {}).get("specified") if isinstance((hw or {}).get("specified"), str) else None,
    )
    if hager_list_price.ngp_for_architect_item(item_type, part, width_in=width_in):
        return True
    if (
        line_source == "MANUAL"
        and line.get("multiplier") is not None
        and str(line.get("price_book_version") or "").strip()
    ):
        return True
    return False


def _apply_list_x(
    line: dict[str, Any],
    *,
    hw: dict[str, Any] | None,
    multiplier: float,
) -> bool:
    matched = (hw or {}).get("matched") if isinstance((hw or {}).get("matched"), dict) else {}
    specified = (hw or {}).get("specified")
    item_type = _item_type(hw, line)
    part_number = _item_part(hw) or str(line.get("part_number") or line.get("part") or "")
    specified_text = specified if isinstance(specified, str) else None
    width_in = hager_list_price.parse_width_inches(
        matched.get("series") if isinstance(matched, dict) else None,
        matched.get("finish") if isinstance(matched, dict) else None,
        specified_text,
        (hw or {}).get("part_number"),
        line.get("part_number"),
        line.get("notes"),
        line.get("description"),
        part_number,
    )
    mapped = hager_list_price.ngp_for_architect_item(
        item_type, part_number, width_in=width_in
    )
    if not mapped:
        return False
    ngp_code, crosswalk = mapped
    quote = hager_list_price.lookup_ngp_list_price(ngp_code, width_in=width_in)
    if not quote:
        return False

    list_price = float(quote["list_price"])
    cost = round(list_price * multiplier, 2)
    qty = float(line.get("quantity") or 1)
    page = quote["source_page"]
    margin = line.get("margin")
    try:
        margin_f = float(margin) if margin is not None else 0.27
    except (TypeError, ValueError):
        margin_f = 0.27
    priced = quote_calc.calculate_line(cost=cost, margin=margin_f, quantity=qty)
    drawing_page = line.get("source_page")
    line["cost"] = priced["cost"]
    line["sale_ea"] = priced["sale_ea"]
    line["ext_price"] = priced["ext_price"]
    line["margin"] = margin_f
    line["cost_source"] = "LIST_X_MULTIPLIER"
    line["cost_source_detail"] = (
        f"{hager_list_price.HAGER_BOOK} p.{page} NGP {ngp_code} MIL list ${list_price:.2f}; "
        f"{crosswalk}; ×{multiplier:g} → cost ${cost:.2f}"
    )
    line["catalog_page"] = page
    if drawing_page in (None, ""):
        line["source_page"] = page
    line["multiplier"] = multiplier
    if not line.get("multiplier_tier"):
        line["multiplier_tier"] = "thresholds_weatherstrip"
    line["price_book_version"] = line.get("price_book_version") or "Hager Price Book #18"
    line["basis"] = f"Hager #18 × {multiplier:g}"
    line["price_status"] = "LIST_X_MULTIPLIER"
    flags = [str(f) for f in (line.get("flags") or []) if f]
    for drop in (
        "requires_page_lookup",
        "manual_page_lookup_pending",
        "requires_price_book_verification",
        "manual_cutoff_vendor",
        "not_phase1",
    ):
        if drop in flags:
            flags.remove(drop)
    if "list_x_backfilled" not in flags:
        flags.append("list_x_backfilled")
    line["flags"] = flags
    return True


def priced_line_metrics(slug: str) -> dict[str, int]:
    """Count total / costed lines from ``priced/line_items.json``."""
    path = storage.project_dir(slug) / "priced" / "line_items.json"
    payload = read_json(path)
    lines: list[Any] = []
    if isinstance(payload, dict):
        rows = payload.get("lines") or payload.get("line_items") or []
        if isinstance(rows, list):
            lines = rows
    elif isinstance(payload, list):
        lines = payload
    total = sum(1 for row in lines if isinstance(row, dict))
    with_cost = sum(
        1
        for row in lines
        if isinstance(row, dict)
        and isinstance(row.get("cost"), (int, float))
        and not isinstance(row.get("cost"), bool)
    )
    return {"total_lines": total, "lines_with_cost": with_cost}


def backfill_priced_lines(slug: str) -> dict[str, int]:
    """Rewrite ``priced/line_items.json`` with deterministic LIST_X costs where possible."""
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
        attempted += 1
        multiplier = float(
            line.get("multiplier")
            or (hw or {}).get("multiplier")
            or _THRESH_WEATHER_MULT
        )
        if _apply_list_x(line, hw=hw, multiplier=multiplier):
            filled += 1
        else:
            skipped += 1

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
            "list_x_backfilled": filled,
            "manual_cutoff_applied": with_cost < total,
        }
        write_json(path, payload)
    return {"attempted": attempted, "filled": filled, "skipped": skipped}
