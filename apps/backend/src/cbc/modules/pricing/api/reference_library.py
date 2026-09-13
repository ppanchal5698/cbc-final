"""Read/write helpers for curated reference data (Mongo-backed).

JSON under REFERENCE_DIR is seed only; live reads/writes go through reference_store.
"""
from __future__ import annotations

import re
from typing import Any

from cbc.modules.pricing.api import reference_store

# The constants the FRP take-off needs before it can convert geometry to quantities.
# opening_handling is guidance, not arithmetic, so it does not gate the status.
FRP_REQUIRED_CONSTANTS = (
    "panel_size",
    "waste_pct",
    "trim_stick_length",
    "adhesive_coverage_sqft_per_unit",
)
FRP_NUMERIC_CONSTANTS = ("waste_pct", "trim_stick_length", "adhesive_coverage_sqft_per_unit")
FRP_EDITABLE_CONSTANTS = FRP_REQUIRED_CONSTANTS + ("opening_handling",)


def load_margins() -> dict[str, Any]:
    """The full margin framework document, structure preserved."""
    return reference_store.get_family_sync("margins")


def update_margins(
    bands: dict[str, float] | None = None,
    accessories: float | None = None,
) -> dict[str, Any]:
    """Edit the margin framework in place and return the updated document."""
    payload = load_margins()
    known = {b.get("key") for b in payload.get("bands", []) if b.get("key")}

    if bands:
        unknown = set(bands) - known
        if unknown:
            raise ValueError(f"unknown margin band(s): {', '.join(sorted(unknown))}")
        for record in payload.get("bands", []):
            key = record.get("key")
            if key in bands:
                margin = float(bands[key])
                if not 0 <= margin < 1:
                    raise ValueError(f"margin for {key!r} must be in [0, 1), got {margin}")
                record["margin"] = margin
                record["divisor"] = round(1 - margin, 4)

    if accessories is not None:
        accessories = float(accessories)
        if not 0 <= accessories < 1:
            raise ValueError(f"accessories margin must be in [0, 1), got {accessories}")
        payload["accessories_derived"] = accessories

    reference_store.put_family_sync("margins", payload)
    from cbc.modules.pricing.api.calc import invalidate_reference_caches

    invalidate_reference_caches()
    return payload


def load_tax_rates() -> dict[str, Any]:
    """The full sales-tax document, structure preserved."""
    return reference_store.get_family_sync("tax")


def update_tax_rates(
    rates: dict[str, float] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert nexus tax rates and/or drop jurisdictions, returning the updated doc."""
    payload = load_tax_rates()
    table = dict(payload.get("rates", {}))

    if rates:
        for code, rate in rates.items():
            rate = float(rate)
            if not 0 <= rate < 1:
                raise ValueError(f"tax rate for {code!r} must be in [0, 1), got {rate}")
            table[code.strip().upper()] = rate

    for code in remove or []:
        table.pop(str(code).strip().upper(), None)

    payload["rates"] = table
    reference_store.put_family_sync("tax", payload)
    from cbc.modules.pricing.api.calc import invalidate_reference_caches

    invalidate_reference_caches()
    return payload


def load_adders() -> dict[str, Any]:
    """The full manual-adders document, structure preserved."""
    return reference_store.get_family_sync("manual_adders")


def update_hager_adders(
    items: dict[str, float] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert or drop Hager list adders and return the updated document."""
    payload = load_adders()
    block = payload.setdefault("hager_list_adders", {})
    rows = list(block.get("items", []))
    by_name = {str(r.get("name")): r for r in rows}

    if items:
        for raw_name, value in items.items():
            name = raw_name.strip()
            if not name:
                raise ValueError("adder name must not be blank")
            value = float(value)
            if value < 0:
                raise ValueError(f"adder {name!r} must not be negative, got {value}")
            if name in by_name:
                by_name[name]["list_adder"] = value
            else:
                row = {"name": name, "list_adder": value}
                rows.append(row)
                by_name[name] = row

    if remove:
        drop = {r.strip() for r in remove}
        rows = [r for r in rows if str(r.get("name")) not in drop]

    block["items"] = rows
    payload["hager_list_adders"] = block
    reference_store.put_family_sync("manual_adders", payload)
    return payload


def load_special_margins() -> dict[str, Any]:
    """The full special-customer-margins document, structure preserved."""
    return reference_store.get_family_sync("special_customer_margins")


def update_special_margins(
    customers: list[dict[str, Any]] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert or drop special-customer margins and return the updated document."""
    payload = load_special_margins()
    rows = list(payload.get("customers", []))
    by_name = {str(c.get("name")): c for c in rows}

    for entry in customers or []:
        name = str(entry.get("name", "")).strip()
        if not name:
            raise ValueError("customer name must not be blank")
        existing = by_name.get(name)
        if existing is None:
            existing = {"name": name}
            rows.append(existing)
            by_name[name] = existing
        if "margin" in entry:
            margin = entry["margin"]
            if margin is not None:
                margin = float(margin)
                if not 0 <= margin < 1:
                    raise ValueError(f"margin for {name!r} must be in [0, 1), got {margin}")
            existing["margin"] = margin
        if "note" in entry:
            existing["note"] = entry["note"]

    if remove:
        drop = {r.strip() for r in remove}
        rows = [c for c in rows if str(c.get("name")) not in drop]

    payload["customers"] = rows
    reference_store.put_family_sync("special_customer_margins", payload)
    return payload


_DEPTH_WHOLE_FRACTION = re.compile(r"^(\d+)\s*-\s*(\d+)\s*/\s*(\d+)$")
_DEPTH_FRACTION = re.compile(r"^(\d+)\s*/\s*(\d+)$")


def _parse_depth_inches(text: str) -> float:
    """Turn a throat-depth label into inches: '5-3/4' -> 5.75, '5.75' -> 5.75."""
    text = text.strip()
    try:
        value = float(text)
    except ValueError:
        whole_fraction = _DEPTH_WHOLE_FRACTION.match(text)
        fraction = _DEPTH_FRACTION.match(text)
        if whole_fraction:
            whole, num, den = (int(g) for g in whole_fraction.groups())
            if den == 0:
                raise ValueError(f"depth {text!r} has a zero denominator")
            value = whole + num / den
        elif fraction:
            num, den = (int(g) for g in fraction.groups())
            if den == 0:
                raise ValueError(f"depth {text!r} has a zero denominator")
            value = num / den
        else:
            raise ValueError(f"could not parse depth {text!r}; use e.g. 5-3/4 or 5.75")
    if value <= 0:
        raise ValueError(f"depth {text!r} must be greater than zero")
    return value


def load_finishes() -> dict[str, Any]:
    """The full finish-crosswalk document, structure preserved."""
    return reference_store.get_family_sync("finishes")


def update_finishes(
    finishes: list[dict[str, Any]] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert or drop finish rows (keyed by us_code) and return the updated document."""
    payload = load_finishes()
    rows = list(payload.get("finishes", []))
    by_code = {str(f.get("us_code")): f for f in rows}

    for entry in finishes or []:
        code = str(entry.get("us_code", "")).strip()
        if not code:
            raise ValueError("us_code must not be blank")
        existing = by_code.get(code)
        if existing is None:
            existing = {"us_code": code}
            rows.append(existing)
            by_code[code] = existing
        for field in ("numeric_code", "description", "premium", "note"):
            if field in entry:
                existing[field] = entry[field]

    if remove:
        drop = {r.strip() for r in remove}
        rows = [f for f in rows if str(f.get("us_code")) not in drop]

    payload["finishes"] = rows
    reference_store.put_family_sync("finishes", payload)
    return payload


def load_frame_depths() -> dict[str, Any]:
    """The full wall-type-to-depth document, structure preserved."""
    return reference_store.get_family_sync("frame_depths")


def update_frame_depths(
    wall_types: list[dict[str, Any]] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert or drop wall-type rows (keyed by type) and return the updated document."""
    payload = load_frame_depths()
    rows = list(payload.get("wall_types", []))
    by_type = {str(w.get("type")): w for w in rows}

    for entry in wall_types or []:
        wall_type = str(entry.get("type", "")).strip()
        if not wall_type:
            raise ValueError("wall type must not be blank")
        existing = by_type.get(wall_type)
        if existing is None:
            existing = {"type": wall_type}
            rows.append(existing)
            by_type[wall_type] = existing
        if "depth" in entry:
            depth = str(entry["depth"]).strip()
            if not depth:
                raise ValueError(f"depth for {wall_type!r} must not be blank")
            existing["depth"] = depth
            existing["depth_inches"] = round(_parse_depth_inches(depth), 4)
        if "note" in entry:
            existing["note"] = entry["note"]

    if remove:
        drop = {r.strip() for r in remove}
        rows = [w for w in rows if str(w.get("type")) not in drop]

    payload["wall_types"] = rows
    reference_store.put_family_sync("frame_depths", payload)
    return payload


def load_frp_constants() -> dict[str, Any]:
    """The full FRP conversion-constants document, structure preserved."""
    return reference_store.get_family_sync("frp_constants")


def update_frp_constants(values: dict[str, Any]) -> dict[str, Any]:
    """Set FRP conversion constants and return the updated document."""
    payload = load_frp_constants()
    for field, value in values.items():
        if field not in FRP_EDITABLE_CONSTANTS:
            raise ValueError(f"unknown FRP constant {field!r}")
        if field in FRP_NUMERIC_CONSTANTS and value is not None:
            value = float(value)
            if value < 0:
                raise ValueError(f"{field} must not be negative, got {value}")
        payload[field] = value

    complete = all(payload.get(field) is not None for field in FRP_REQUIRED_CONSTANTS)
    payload["status"] = "SET" if complete else "PENDING"
    reference_store.put_family_sync("frp_constants", payload)
    return payload


def load_vendor_tiers() -> dict[str, Any]:
    return reference_store.get_family_sync("vendor_tiers")


def update_vendor_tiers(payload: dict[str, Any]) -> dict[str, Any]:
    reference_store.put_family_sync("vendor_tiers", payload)
    return payload


def load_special_nets() -> dict[str, Any]:
    return reference_store.get_family_sync("hager_special_nets")


def update_special_nets(payload: dict[str, Any]) -> dict[str, Any]:
    reference_store.put_family_sync("hager_special_nets", payload)
    return payload


def load_lite_kit_prices() -> dict[str, Any]:
    return reference_store.get_family_sync("lite_kit_prices")


def update_lite_kit_prices(payload: dict[str, Any]) -> dict[str, Any]:
    reference_store.put_family_sync("lite_kit_prices", payload)
    from cbc.modules.pricing.api.calc import invalidate_reference_caches

    invalidate_reference_caches()
    return payload


def update_vendor_categories(vendor_key: str, categories: dict[str, float]) -> dict[str, Any]:
    """PATCH categories for one vendor in vendor_tiers."""
    payload = load_vendor_tiers()
    needle = vendor_key.strip().lower()
    for record in payload.get("vendors", []):
        names = {str(record.get("key", "")).lower(), str(record.get("name", "")).lower()}
        if needle not in names:
            continue
        cleaned: dict[str, float] = {}
        for raw_key, value in categories.items():
            key = str(raw_key).strip().lower().replace(" ", "_").replace("-", "_")
            amount = float(value)
            if amount < 0:
                raise ValueError(f"multiplier for {key!r} must not be negative")
            cleaned[key] = amount
        record["categories"] = cleaned
        update_vendor_tiers(payload)
        return payload
    raise ValueError(f"vendor {vendor_key!r} not in vendor_tiers")


def update_special_net_items(
    items: list[dict[str, Any]] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert special-net rows by part_number; remove by part_number."""
    payload = load_special_nets()
    rows = list(payload.get("items", []))
    by_part = {str(r.get("part_number", "")).strip().upper(): r for r in rows if r.get("part_number")}

    for item in items or []:
        part = str(item.get("part_number") or "").strip().upper()
        if not part:
            raise ValueError("special net item needs part_number")
        net = item.get("net_price")
        if net is not None and float(net) < 0:
            raise ValueError(f"net_price for {part} must not be negative")
        if part in by_part:
            by_part[part].update({k: v for k, v in item.items() if v is not None})
            by_part[part]["part_number"] = part
        else:
            row = dict(item)
            row["part_number"] = part
            rows.append(row)
            by_part[part] = row

    if remove:
        drop = {str(p).strip().upper() for p in remove}
        rows = [r for r in rows if str(r.get("part_number", "")).strip().upper() not in drop]

    payload["items"] = rows
    return update_special_nets(payload)


def update_stock_items(
    vendor_key: str,
    items: list[dict[str, Any]] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    payload = load_stock_list(vendor_key)
    if payload is None:
        raise ValueError(f"no stock family for vendor {vendor_key!r}")
    rows = list(payload.get("items", []))
    by_part = {str(r.get("part_number", "")).strip().upper(): r for r in rows if r.get("part_number")}

    for item in items or []:
        part = str(item.get("part_number") or "").strip().upper()
        if not part:
            raise ValueError("stock item needs part_number")
        if part in by_part:
            by_part[part].update({k: v for k, v in item.items() if v is not None})
            by_part[part]["part_number"] = part
        else:
            row = dict(item)
            row["part_number"] = part
            rows.append(row)
            by_part[part] = row

    if remove:
        drop = {str(p).strip().upper() for p in remove}
        rows = [r for r in rows if str(r.get("part_number", "")).strip().upper() not in drop]

    payload["items"] = rows
    return update_stock_list(vendor_key, payload)


def get_vendor_tier(vendor: str, category: str | None = None) -> dict[str, Any]:
    """Same shape as catalog get_multiplier — shared with MCP."""
    data = load_vendor_tiers()
    needle = str(vendor or "").strip().lower()
    for record in data.get("vendors", []):
        names = {str(record.get("key", "")).lower(), str(record.get("name", "")).lower()}
        if needle not in names:
            continue
        categories = record.get("categories") or {}
        if category and categories:
            key = str(category).strip().lower().replace(" ", "_").replace("-", "_")
            if key in categories:
                return {
                    "vendor": record.get("name"),
                    "category": key,
                    "multiplier": categories[key],
                    "effective_date": record.get("effective_date"),
                    "account": record.get("account"),
                    "source": record.get("source"),
                }
            return {
                "vendor": record.get("name"),
                "category": category,
                "multiplier": None,
                "available_categories": sorted(categories),
                "note": "Unknown category for this vendor - do not guess, ask the estimator.",
            }
        return {
            "vendor": record.get("name"),
            "tier": record.get("tier"),
            "multiplier": record.get("multiplier"),
            "categories": categories or None,
            "effective_date": record.get("effective_date"),
            "account": record.get("account"),
            "note": record.get("note"),
            "source": record.get("source"),
        }
    return {
        "vendor": vendor,
        "multiplier": None,
        "note": "Vendor not in the tier sheet. Price manually (MANUAL cut-off) - never guess.",
    }


def get_special_net(vendor: str, part_number: str) -> dict[str, Any] | None:
    vendor_key = str(vendor or "").strip().lower()
    if vendor_key != "hager":
        return None
    payload = load_special_nets()
    upper = str(part_number or "").strip().upper()
    keys = {upper, upper.split("-")[0].split()[0]} if upper else set()
    for row in payload.get("items", []):
        part = str(row.get("part_number", "")).strip().upper()
        if part in keys:
            return {
                "vendor": vendor_key,
                "part_number": part,
                "net_price": row["net_price"],
                "item_code": row.get("item_code"),
                "section": row.get("section"),
                "source_page": row.get("source_page"),
                "effective_date": payload.get("effective_date"),
                "source": payload.get("source"),
            }
    return None


def get_special_customer_margin(customer: str) -> dict[str, Any] | None:
    needle = str(customer or "").strip().lower()
    for row in load_special_margins().get("customers", []):
        if str(row.get("name", "")).strip().lower() == needle:
            return dict(row)
    return None


def delete_family_entry(family: str, key: str) -> dict[str, Any]:
    """Remove one map-like entry from a family document."""
    key = str(key).strip()
    if family == "tax":
        return update_tax_rates(remove=[key])
    if family == "finishes":
        return update_finishes(remove=[key])
    if family == "frame_depths":
        return update_frame_depths(remove=[key])
    if family == "hager_special_nets":
        return update_special_net_items(remove=[key])
    if family in ("hager_top10_stock", "allegion_stock"):
        vendor = "hager" if family.startswith("hager") else "allegion"
        return update_stock_items(vendor, remove=[key])
    if family == "manual_adders":
        return update_hager_adders(remove=[key])
    if family == "special_customer_margins":
        return update_special_margins(remove=[key])
    raise ValueError(f"family {family!r} does not support entry delete")


def load_custom_other_matrix() -> dict[str, Any]:
    return reference_store.get_family_sync("custom_other_matrix")


def update_custom_other_matrix(payload: dict[str, Any]) -> dict[str, Any]:
    reference_store.put_family_sync("custom_other_matrix", payload)
    return payload


def sync_vendor_categories(vendor_key: str, categories: dict[str, float]) -> None:
    """Keep vendor_tiers aligned when purchasing edits category multipliers."""
    try:
        payload = load_vendor_tiers()
    except Exception:
        return
    for record in payload.get("vendors", []):
        if record.get("key") != vendor_key:
            continue
        record["categories"] = categories
        update_vendor_tiers(payload)
        return


def stock_family_for(vendor_key: str) -> str | None:
    """Map vendor key to a referenceData family id."""
    key = vendor_key.lower().strip()
    for family in (f"{key}_top10_stock", f"{key}_stock"):
        if family in reference_store.FAMILIES:
            return family
    return None


def load_stock_list(vendor_key: str) -> dict[str, Any] | None:
    family = stock_family_for(vendor_key)
    if family is None:
        return None
    try:
        return reference_store.get_family_sync(family)
    except Exception:
        return None


def update_stock_list(vendor_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    family = stock_family_for(vendor_key)
    if family is None:
        raise ValueError(f"no stock family for vendor {vendor_key!r}")
    reference_store.put_family_sync(family, payload)
    return payload


def is_stock_part(vendor_key: str, part_number: str) -> dict[str, Any]:
    """NR-6 stock-list lookup. Returns None for stock when no list is on file."""
    payload = load_stock_list(vendor_key)
    if payload is None:
        return {
            "vendor": vendor_key,
            "part_number": part_number,
            "stock": None,
            "note": "No top-10 stock list on file for this vendor (NR-6 pending).",
        }

    needle = part_number.strip().upper()
    base = needle.split("-")[0].split()[0]
    parts = {
        str(item.get("part_number", "")).strip().upper()
        for item in payload.get("items", [])
        if item.get("part_number")
    }
    matched = needle in parts or base in parts
    return {
        "vendor": vendor_key,
        "part_number": part_number,
        "stock": matched,
        "list_status": payload.get("status"),
        "status_note": payload.get("status_note"),
        "source": payload.get("source"),
    }


_WALL_TYPE_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("6\" metal stud", "6 inch metal stud", "6\" mtl stud", "6 mtl stud"),
     "6 inch metal stud with 5/8 drywall"),
    (("cmu", "masonry", "block", "brick"), "masonry"),
    (("wood stud", "wood frame", "wood-frame", "timber"), "wood-frame"),
    (("1/2\" drywall", "half inch drywall", "1/2 gyp", "half-inch drywall"),
     "half-inch drywall"),
    (("drywall", "gypsum", "gyp", "metal stud", "mtl stud", "stud"), "drywall"),
)


def depth_for_wall_type(wall_type: str | None) -> dict[str, Any] | None:
    """The frame throat a wall construction implies, or None when it is unclear."""
    if not wall_type or not str(wall_type).strip():
        return None
    text = " ".join(str(wall_type).lower().split())

    table = load_frame_depths()
    by_type = {str(w.get("type", "")).lower(): w for w in table.get("wall_types", [])}

    if text in by_type:
        return dict(by_type[text])
    for needles, canonical in _WALL_TYPE_ALIASES:
        if any(needle in text for needle in needles):
            entry = by_type.get(canonical)
            if entry:
                return {**entry, "matched_on": canonical}
    return None


_FINISH_TOKEN = re.compile(r"^(?:US)?\s*(\d{1,3}[A-Z]?)$", re.IGNORECASE)


def resolve_finish(text: str | None) -> dict[str, Any] | None:
    """Read a finish written in either nomenclature, or say it is ambiguous."""
    if not text or not str(text).strip():
        return None
    raw = " ".join(str(text).upper().split())

    finishes = load_finishes().get("finishes", [])
    by_us = {str(f.get("us_code", "")).upper(): f for f in finishes}

    if raw in by_us:
        return {**by_us[raw], "matched_on": "us_code"}

    token = _FINISH_TOKEN.match(raw)
    if not token:
        return None
    body = token.group(1).upper()

    if f"US{body}" in by_us:
        return {**by_us[f"US{body}"], "matched_on": "us_code"}

    numeric = [f for f in finishes if str(f.get("numeric_code") or "") == body]
    if len(numeric) == 1:
        return {**numeric[0], "matched_on": "numeric_code"}
    if len(numeric) > 1:
        return {
            "ambiguous": True,
            "numeric_code": body,
            "candidates": [f.get("us_code") for f in numeric],
            "matched_on": "numeric_code",
            "note": (
                f"{body} is shared by {' and '.join(str(f.get('us_code')) for f in numeric)}"
                " in the CBC crosswalk. They are different finishes - confirm which"
                " one the schedule means before matching a part."
            ),
        }
    return None


def normalize_finish_value(text: str | None) -> dict[str, Any]:
    """Canonicalize a schedule finish for storage on an opening / line item (NR-3)."""
    if not text or not str(text).strip():
        return {"value": None, "flags": []}

    raw = str(text).strip()
    resolved = resolve_finish(raw)
    if resolved is None:
        return {"value": raw, "flags": ["finish_unrecognized"]}
    if resolved.get("ambiguous"):
        return {"value": raw, "flags": ["finish_ambiguous"]}

    us = resolved.get("us_code")
    num = resolved.get("numeric_code")
    if us and num:
        value = f"{us} ({num})"
    elif us:
        value = str(us)
    else:
        value = raw
    return {"value": value, "flags": []}


def find_adders(names: list[str], vendor: str = "hager") -> dict[str, Any]:
    """The list adders CBC has values for, matched by name."""
    table = load_adders()
    catalogue = table.get(f"{vendor.lower()}_list_adders", {}) or {}
    items = catalogue.get("items", [])
    by_name = {str(i.get("name", "")).lower(): i for i in items}

    matched, unpriced = [], []
    for name in names:
        needle = str(name or "").strip().lower()
        if not needle:
            continue
        hit = by_name.get(needle) or next(
            (i for key, i in by_name.items() if needle in key or key in needle), None
        )
        (matched.append(hit) if hit else unpriced.append(name))
    return {
        "vendor": vendor,
        "matched": matched,
        "unpriced": unpriced,
        "source": catalogue.get("source"),
        "application": catalogue.get("application"),
        "note": (
            "Adders are LIST values - add to the list price, then apply the "
            "vendor multiplier to the sum."
        ),
        "pending": table.get("pending", []) if unpriced else [],
    }
