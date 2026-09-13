"""Quote arithmetic - pure rules, no I/O.

Formulas (confirmed, Requirements Matrix 5.0):
    Sale $ EA = Cost / (1 - margin)
    Unit      = Sale $ EA
    Ext       = Unit x Qty
    Sub-total = SUM(Ext) per group
    Grand tot = SUM(sub-totals)

Live margin bands and tax rates are loaded by `cbc.modules.pricing.api.reference_calc` and
passed in. Defaults below are the fallback when nothing has been seeded yet.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

DEFAULT_BANDS = {
    "commodity": 0.27,
    "restroom_partitions": 0.35,
    "specialty": 0.40,
    "custom_built": 0.25,
    "accessories": 0.56,
}

DEFAULT_TAX_RATES = {"OH": 0.08, "KY": 0.065}

_STATE_ALIASES = {
    "OHIO": "OH",
    "KENTUCKY": "KY",
}


def normalise_state(state: str | None, rates: dict[str, float] | None = None) -> str | None:
    """Map full state names and abbreviations to the tax table's keys."""
    if not state:
        return None
    cleaned = str(state).strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper in _STATE_ALIASES:
        return _STATE_ALIASES[upper]
    known = rates if rates is not None else DEFAULT_TAX_RATES
    if upper in DEFAULT_TAX_RATES or upper in known:
        return upper
    return upper if len(upper) == 2 else None


def _money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_line(cost: float, margin: float, quantity: float = 1) -> dict[str, Any]:
    if not 0 <= margin < 1:
        raise ValueError(f"margin must be a fraction in [0, 1), got {margin}")
    if not math.isfinite(cost):
        raise ValueError(f"cost must be a finite number, got {cost}")
    if cost < 0:
        raise ValueError(f"cost must not be negative, got {cost}")
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError(f"quantity must be a non-negative finite number, got {quantity}")
    divisor = 1 - margin
    exact_ea = Decimal(str(cost)) / Decimal(str(divisor))
    sale_ea = _money(exact_ea)
    return {
        "cost": _money(cost),
        "margin": margin,
        "divisor": round(divisor, 4),
        "quantity": quantity,
        "sale_ea": sale_ea,
        "unit_sale_ea": sale_ea,
        "ext_price": _money(exact_ea * Decimal(str(quantity))),
        "formula": "sale_ea = cost / (1 - margin); ext_price = sale_ea * quantity",
    }


def apply_margin(
    cost: float,
    product_type: str,
    override_margin: float | None = None,
    override_reason: str | None = None,
    *,
    bands_map: dict[str, float] | None = None,
) -> dict[str, Any]:
    known = bands_map if bands_map is not None else DEFAULT_BANDS
    if product_type not in known:
        raise ValueError(f"unknown product_type {product_type!r}; known: {sorted(known)}")
    default_margin = known[product_type]
    margin = default_margin if override_margin is None else float(override_margin)
    result = calculate_line(cost=cost, margin=margin, quantity=1)
    result.update(
        {
            "product_type": product_type,
            "default_margin": default_margin,
            "overridden": override_margin is not None,
            "override_reason": override_reason,
            "margin_check": validate_margin(product_type, margin, bands_map=known),
        }
    )
    if override_margin is not None and not override_reason:
        result["warning"] = (
            "Margin overridden with no recorded reason - this is what the "
            "margin-governance flag exists for."
        )
    return result


def validate_margin(
    product_type: str,
    applied_margin: float,
    *,
    bands_map: dict[str, float] | None = None,
) -> dict[str, Any]:
    known = bands_map if bands_map is not None else DEFAULT_BANDS
    floor = known.get(product_type)
    if floor is None:
        return {"status": "unknown_product_type", "product_type": product_type}
    below = applied_margin < floor - 1e-9
    return {
        "status": "fail" if below else "pass",
        "product_type": product_type,
        "floor": floor,
        "applied_margin": applied_margin,
        "flag": "below_band" if below else None,
        "note": "Flagged only. Approval routing is deferred (NFR-8).",
    }


def _line_ext_price(item: dict[str, Any]) -> float:
    ext = item.get("ext_price")
    if ext is not None:
        try:
            return float(ext)
        except (TypeError, ValueError):
            return 0.0
    sale = item.get("sale_ea")
    if sale is None:
        return 0.0
    try:
        qty = item.get("quantity", 1)
        return float(sale) * float(qty)
    except (TypeError, ValueError):
        return 0.0


def compute_totals(
    line_items: list[dict[str, Any]],
    project_state: str | None = None,
    *,
    tax_map: dict[str, float] | None = None,
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for item in line_items:
        group = str(item.get("group") or "ungrouped")
        ext = _line_ext_price(item)
        bucket = groups.setdefault(group, {"group": group, "line_count": 0, "subtotal": 0.0})
        bucket["line_count"] += 1
        bucket["subtotal"] = _money(bucket["subtotal"] + ext)

    subtotal = _money(sum(g["subtotal"] for g in groups.values()))
    rates = tax_map if tax_map is not None else DEFAULT_TAX_RATES
    state = normalise_state(project_state, rates)
    tax_rate = rates.get(state or "", 0.0)
    tax = _money(subtotal * tax_rate)

    return {
        "groups": sorted(groups.values(), key=lambda g: g["group"]),
        "subtotal": subtotal,
        "freight": None,
        "freight_note": "TBD - freight is not quoted at estimate stage",
        "project_state": state or None,
        "tax_rate": tax_rate,
        "tax": tax,
        "tax_note": (
            "Sales tax applies to Ohio and Kentucky only; all other states and Canada are untaxed."
            if state
            else "Project state unknown - tax UNRESOLVED, flag for the estimator."
        ),
        "grand_total": _money(subtotal + tax),
    }


def cost_from_list(
    list_price: float,
    multiplier: float,
    adders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if list_price < 0:
        raise ValueError(f"list price must not be negative, got {list_price}")
    if not 0 < multiplier <= 1:
        raise ValueError(f"multiplier must be a fraction in (0, 1], got {multiplier}")

    applied = []
    total_adders = Decimal("0")
    for adder in adders or []:
        value = Decimal(str(adder.get("list_adder", 0) or 0))
        total_adders += value
        applied.append(
            {
                "name": adder.get("name", "unnamed adder"),
                "list_adder": _money(value),
                "cost_effect": _money(value * Decimal(str(multiplier))),
            }
        )

    list_total = Decimal(str(list_price)) + total_adders
    return {
        "list_price": _money(list_price),
        "adders": applied,
        "adders_list_total": _money(total_adders),
        "list_with_adders": _money(list_total),
        "multiplier": multiplier,
        "cost": _money(list_total * Decimal(str(multiplier))),
        "formula": "cost = (list + adders) x multiplier",
    }


def ceil_to_grid(value: float, keys: list[int]) -> int | None:
    """Next-largest even inch per NGP lite-kit sizing rule."""
    if not keys or value <= 0:
        return None
    target = int(math.ceil(value))
    if target % 2 == 1:
        target += 1
    for key in sorted(keys):
        if key >= target:
            return key
    return max(keys)


def lookup_lite_kit_list_price_from_data(
    data: dict[str, Any] | None,
    width_in: float,
    height_in: float,
    pdf_page: int | None = None,
) -> dict[str, Any]:
    """NR-1: list price from already-loaded lite_kit_prices for a width x height."""
    if not data:
        return {"list_price": None, "note": "lite_kit_prices not available"}
    if width_in <= 0 or height_in <= 0:
        raise ValueError("width_in and height_in must be positive")

    tables = data.get("tables") or []
    if pdf_page is not None:
        tables = [t for t in tables if t.get("pdf_page") == pdf_page] or tables

    for table in tables:
        widths = [int(w) for w in table.get("widths") or []]
        prices = table.get("prices") or {}
        height_key = ceil_to_grid(height_in, sorted(int(h) for h in prices))
        width_key = ceil_to_grid(width_in, widths)
        if height_key is None or width_key is None:
            continue
        row = prices.get(str(height_key), {})
        list_price = row.get(str(width_key))
        if list_price is None:
            continue
        return {
            "list_price": float(list_price),
            "width_used": width_key,
            "height_used": height_key,
            "pdf_page": table.get("pdf_page"),
            "source": "referenceData/lite_kit_prices",
            "note": "Apply vendor multiplier via cost_from_list; outside table range → vendor RFQ.",
        }

    return {
        "list_price": None,
        "width_in": width_in,
        "height_in": height_in,
        "note": "Outside printed lite-kit table range — mark VENDOR_RFQ (NR-8).",
    }
