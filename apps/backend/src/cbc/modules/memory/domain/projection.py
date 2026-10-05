"""The system of record, turned into the rows the memory graph is built from.

Pure: documents in, plain dicts out, no I/O. The curator hands these rows to
Cypher in batches. Each row carries its `key` (unique within its label), so a
sync MERGEs on it and running one twice changes nothing.

Every value here is copied from a document someone can open - a reference
family, a catalog row, an approved quote line. Nothing is inferred, so nothing
learned can be wrong in a way the source is not.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from typing import Any

MAX_DATA_JSON = 200_000  # a whole reference family, kept readable on its node


def key(name: Any) -> str:
    """One key per real-world name: `National Guard` and `national_guard` are one vendor."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scalar(value: Any) -> Any:
    """A Neo4j property value: scalars as they are, anything nested as JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value):
        return value
    return json.dumps(value, default=str)


# ── reference data and the catalog ───────────────────────────────────────────


def vendor_rows(tiers: dict[str, Any], books: Iterable[dict[str, Any]], manufacturers: Iterable[str]) -> list[dict[str, Any]]:
    """Every vendor any source names: the tier table, a price book, a catalog row."""
    found: dict[str, dict[str, Any]] = {}
    for vendor in tiers.get("vendors") or []:
        k = key(vendor.get("key") or vendor.get("name"))
        if k:
            found[k] = {
                "key": k,
                "name": vendor.get("name") or k,
                "program": vendor.get("tier"),
                "account": vendor.get("account"),
                "shareOfVolume": _num(vendor.get("share_of_volume")),
                "priceBook": vendor.get("price_book"),
                "note": vendor.get("note"),
                "excludedReason": None,
            }
    for excluded in tiers.get("excluded") or []:
        k = key(excluded.get("name"))
        if k:
            found.setdefault(k, {"key": k, "name": excluded.get("name")})["excludedReason"] = excluded.get("reason")
    for book in books:
        k = key(book.get("vendor"))
        if k:
            found.setdefault(k, {"key": k, "name": str(book.get("vendor")).replace("_", " ").title()})
    for name in manufacturers:
        k = key(name)
        if k:
            found.setdefault(k, {"key": k, "name": name})
    return list(found.values())


def multiplier_rows(tiers: dict[str, Any]) -> list[dict[str, Any]]:
    """A vendor's multiplier: one per product category where the vendor prices by
    category (Hager), else the single account multiplier."""
    rows: list[dict[str, Any]] = []
    for vendor in tiers.get("vendors") or []:
        vk = key(vendor.get("key") or vendor.get("name"))
        if not vk:
            continue
        common = {
            "vendor": vk,
            "program": vendor.get("tier"),
            "account": vendor.get("account"),
            "effective": vendor.get("effective_date"),
            "source": vendor.get("source"),
        }
        discounts = vendor.get("discounts") or {}
        for category, value in (vendor.get("categories") or {}).items():
            rows.append({**common, "key": f"{vk}:{category}", "category": category,
                         "value": _num(value), "discount": discounts.get(category)})
        if vendor.get("multiplier") is not None:
            rows.append({**common, "key": f"{vk}:all", "category": "all",
                         "value": _num(vendor.get("multiplier")), "discount": None})
    return rows


def price_book_rows(books: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": str(book["_id"]),
            "vendor": key(book.get("vendor")),
            "name": book.get("program") or book.get("filename") or str(book["_id"]),
            "filename": book.get("filename"),
            "kind": book.get("kind"),
            "effective": _iso(book.get("effective")),
            "listPrices": (book.get("entries") or {}).get("count"),
        }
        for book in books
    ]


def catalog_rows(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        part = str(item.get("part") or "").strip()
        vendor = key(item.get("manufacturer"))
        if not part:
            continue
        rows.append({
            "key": f"{vendor}:{part}",
            "part": part,
            "vendor": vendor,
            "description": item.get("description"),
            "division": item.get("division"),
            "category": item.get("category"),
            "model": item.get("model"),
            "cost": _num(item.get("cost")),
            "listPrice": _num(item.get("listPrice")),
            "priceBasis": item.get("priceBasis"),
            "availability": item.get("availability"),
            "priceBook": str(item["priceBookId"]) if item.get("priceBookId") else None,
        })
    return rows


def customer_rows(special_margins: dict[str, Any]) -> list[dict[str, Any]]:
    """Accounts with a special margin. A null margin is recorded as null - CBC still
    owes the value - never as zero."""
    return [
        {
            "key": key(c.get("name")),
            "name": c.get("name"),
            "specialMargin": _num(c.get("margin")),
            "specialMarginNote": c.get("note"),
            "source": c.get("source"),
        }
        for c in special_margins.get("customers") or []
        if key(c.get("name"))
    ]


def frame_depth_rows(frame_depths: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": key(w.get("type")),
            "wallType": w.get("type"),
            "depth": w.get("depth"),
            "inches": _num(w.get("depth_inches")),
            "note": w.get("note"),
        }
        for w in frame_depths.get("wall_types") or []
        if key(w.get("type"))
    ]


_FRP_META = {"status", "blocking", "description", "source"}


def frp_rows(frp: dict[str, Any]) -> list[dict[str, Any]]:
    """One node per conversion constant; a constant CBC has not supplied yet is null."""
    return [
        {
            "key": name,
            "name": name,
            "value": _scalar(value),
            "note": frp.get(f"{name}_note"),
            "status": frp.get("status"),
        }
        for name, value in frp.items()
        if name not in _FRP_META and not name.endswith("_note")
    ]


def finish_rows(finishes: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": str(f.get("us_code")).upper(),
            "usCode": f.get("us_code"),
            "bhma": f.get("numeric_code"),
            "description": f.get("description"),
            "premium": bool(f.get("premium")),
            "note": f.get("note"),
        }
        for f in finishes.get("finishes") or []
        if f.get("us_code")
    ]


def tax_rows(tax: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": str(state).upper(), "jurisdiction": str(state).upper(), "rate": _num(rate)}
            for state, rate in (tax.get("rates") or {}).items()]


def special_net_rows(nets: dict[str, Any]) -> list[dict[str, Any]]:
    vendor = key(nets.get("vendor"))
    return [
        {
            "key": f"{vendor}:{item.get('item_code') or item.get('part_number')}",
            "vendor": vendor,
            "itemCode": item.get("item_code"),
            "part": item.get("part_number"),
            "description": item.get("description"),
            "netPrice": _num(item.get("net_price")),
            "section": item.get("section"),
            "sourcePage": item.get("source_page"),
            "effective": nets.get("effective_date"),
        }
        for item in nets.get("items") or []
        if item.get("item_code") or item.get("part_number")
    ]


def margin_band_rows(margins: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": band.get("key"),
            "name": band.get("name"),
            "margin": _num(band.get("margin")),
            "divisor": _num(band.get("divisor")),
            "examples": [str(e) for e in band.get("examples") or []],
        }
        for band in margins.get("bands") or []
        if band.get("key")
    ]


def family_rows(families: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every reference family as a node, its whole document kept on it as JSON."""
    rows = []
    for name, data in families.items():
        data = data or {}
        rows.append({
            "key": name,
            "name": name,
            "description": data.get("description"),
            "status": data.get("status"),
            "source": data.get("source"),
            "dataJson": json.dumps(data, default=str)[:MAX_DATA_JSON],
        })
    return rows


def learned_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """What estimators confirmed a specification means (FR-13)."""
    out = []
    for row in rows:
        vendor = key(row.get("manufacturer"))
        part = str(row.get("part") or "").strip()
        if not row.get("specKey") or not part:
            continue
        out.append({
            "specKey": row["specKey"],
            "spec": row.get("specSample"),
            "itemKey": f"{vendor}:{part}",
            "vendor": vendor,
            "part": part,
            "confirmCount": int(row.get("confirmCount") or 0),
            "rejectCount": int(row.get("rejectCount") or 0),
            "lastConfirmedAt": _iso(row.get("lastConfirmedAt")),
            "lastConfirmedBy": row.get("lastConfirmedBy"),
        })
    return out


# ── a successful bid ─────────────────────────────────────────────────────────


def _seconds(start: Any, end: Any) -> float | None:
    try:
        return round((end - start).total_seconds(), 1)
    except (TypeError, AttributeError):
        return None


def bid_rows(
    project: dict[str, Any],
    approval: dict[str, Any],
    lines: list[dict[str, Any]],
    openings: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    spec_key: Callable[[Any], str],
) -> dict[str, Any]:
    """One approved bid: who it was for, what it contained, what each line became,
    and the workflow that produced it."""
    bid_key = str(project["_id"])
    totals = approval.get("totalsSnapshot") or {}
    priced = [line for line in lines if line.get("cost") is not None]
    steps = []
    for order, job in enumerate(jobs, start=1):
        provider = job.get("provider")
        steps.append({
            "key": f"{bid_key}:{job['_id']}",
            "order": order,
            "type": job.get("type"),
            "status": job.get("status"),
            "attempts": int(job.get("attempts") or 0),
            "errorCode": job.get("errorCode"),
            "provider": provider.get("mode") if isinstance(provider, dict) else provider,
            "durationS": _seconds(job.get("startedAt"), job.get("finishedAt")),
            "at": _iso(job.get("createdAt")),
        })

    sets: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for line in lines:
        group = str(line.get("group") or "Ungrouped")
        set_key = f"{bid_key}:{group}"
        sets.setdefault(set_key, {"key": set_key, "name": group, "division": line.get("division")})
        vendor = key(line.get("manufacturer"))
        part = str(line.get("part") or "").strip()
        spec = " ".join(str(v) for v in (line.get("manufacturer"), part, line.get("description")) if v)
        sk = spec_key(spec)
        if not sk:
            continue
        items.append({
            "set": set_key,
            "specKey": sk,
            "spec": spec,
            "part": part or None,
            "vendor": vendor or None,
            "itemKey": f"{vendor}:{part}" if vendor and part else None,
            "qty": _num(line.get("qty")),
            "cost": _num(line.get("cost")),
            "costSource": line.get("costSource"),
            "costSourceDetail": line.get("costSourceDetail"),
            "margin": _num(line.get("margin")),
            "sell": _num(line.get("sell")),
            "extended": _num(line.get("extended")),
            "priceStatus": line.get("priceStatus"),
            "addedByHand": bool(line.get("addedByHand")),
            "marginOverridden": bool(line.get("marginOverridden")),
            "multiplierTier": line.get("multiplierTier"),
            "priceBookVersion": line.get("priceBookVersion"),
            "sourcePage": line.get("sourcePage"),
        })

    return {
        "bid": {
            "key": bid_key,
            "code": project.get("code"),
            "name": project.get("name"),
            "brand": project.get("brand"),
            "gc": project.get("gc"),
            "architect": project.get("architect"),
            "approvedBy": approval.get("approvedBy"),
            "approvedAt": _iso(approval.get("approvedAt")),
            "total": _num(totals.get("grandTotal")),
            "cost": _num(totals.get("cost")),
            "margin": _num(totals.get("margin")),
            "lineCount": len(lines),
            "pricedLineCount": len(priced),
            "manualLineCount": sum(1 for line in lines if line.get("costSource") == "MANUAL"),
            "handLineCount": sum(1 for line in lines if line.get("addedByHand")),
            "openingCount": len(openings),
            "stepCount": len(steps),
            "retries": sum(max(0, s["attempts"] - 1) for s in steps),
            "failedSteps": sum(1 for s in steps if s["status"] in ("failed", "dead")),
        },
        "brands": [{"key": key(project["brand"]), "name": project["brand"]}] if key(project.get("brand")) else [],
        "gcs": [{"key": key(project["gc"]), "name": project["gc"]}] if key(project.get("gc")) else [],
        "architects": [{"key": key(project["architect"]), "name": project["architect"]}] if key(project.get("architect")) else [],
        "sets": list(sets.values()),
        "items": items,
        "steps": steps,
    }
