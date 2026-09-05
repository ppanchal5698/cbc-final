"""Quote arithmetic - the only place money math happens in this system.

Formulas (confirmed, Requirements Matrix 5.0):
    Sale $ EA = Cost / (1 - margin)
    Unit      = Sale $ EA
    Ext       = Unit x Qty
    Sub-total = SUM(Ext) per group
    Grand tot = SUM(sub-totals)

Legacy "unit weight" is deliberately absent - it was removed in the 14 Jul session.
Margin bands: .claude/memory/margin_sheet.md

This lives here rather than inside the calc-engine MCP server because both the
server and the API need it, and the API used to get at it by exec-ing the
server's module through a custom loader and calling a private function. Same
arithmetic, one implementation, no transport in the middle: `mcp-servers/
calc-engine/server.py` is now an adapter over this module.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Fallback if the reference library is missing; Mongo (via reference_store) is the source of truth.
DEFAULT_BANDS = {
    "commodity": 0.27,
    "restroom_partitions": 0.35,
    "specialty": 0.40,
    "custom_built": 0.25,
    "accessories": 0.56,
}

# Sales tax applies only where CBC has nexus (.claude/memory/sales_tax_rules.md).
# The JSON file is the source of truth; this is the fallback if it is missing.
DEFAULT_TAX_RATES = {"OH": 0.08, "KY": 0.065}

_STATE_ALIASES = {
    "OHIO": "OH",
    "KENTUCKY": "KY",
}


def normalise_state(state: str | None) -> str | None:
    """Map full state names and abbreviations to the tax table's keys."""
    if not state:
        return None
    cleaned = str(state).strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper in _STATE_ALIASES:
        return _STATE_ALIASES[upper]
    if upper in DEFAULT_TAX_RATES or upper in tax_rates():
        return upper
    return upper if len(upper) == 2 else None


def _money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


_bands_cache: tuple[Any, dict[str, float]] | None = None
_tax_cache: tuple[Any, dict[str, float]] | None = None
_lite_kit_cache: dict[str, Any] | None = None


def invalidate_reference_caches() -> None:
    """Call after Admin updates margins/tax/lite-kit in Mongo."""
    global _bands_cache, _tax_cache, _lite_kit_cache
    _bands_cache = None
    _tax_cache = None
    _lite_kit_cache = None
    from cbc.services import reference_store

    reference_store.invalidate("margins")
    reference_store.invalidate("tax")
    reference_store.invalidate("lite_kit_prices")


def bands() -> dict[str, float]:
    """The margin bands from Mongo (seed JSON fallback)."""
    global _bands_cache
    from cbc.services import reference_library as reflib

    try:
        data = reflib.load_margins()
    except Exception:
        return dict(DEFAULT_BANDS)
    stamp = tuple(
        (b.get("key"), b.get("margin")) for b in data.get("bands", []) if b.get("key")
    ) + (("accessories", data.get("accessories_derived")),)
    if _bands_cache and _bands_cache[0] == stamp:
        return dict(_bands_cache[1])
    bands_map = {b["key"]: float(b["margin"]) for b in data.get("bands", []) if "key" in b}
    if "accessories_derived" in data and data["accessories_derived"] is not None:
        bands_map["accessories"] = float(data["accessories_derived"])
    result = bands_map or dict(DEFAULT_BANDS)
    _bands_cache = (stamp, result)
    return dict(result)


def tax_rates() -> dict[str, float]:
    """Nexus tax rates from Mongo (seed JSON fallback)."""
    global _tax_cache
    from cbc.services import reference_library as reflib

    try:
        data = reflib.load_tax_rates()
    except Exception:
        return dict(DEFAULT_TAX_RATES)
    if "rates" not in data:
        return dict(DEFAULT_TAX_RATES)
    result = {str(code).upper(): float(rate) for code, rate in (data["rates"] or {}).items()}
    stamp = tuple(sorted(result.items()))
    if _tax_cache and _tax_cache[0] == stamp:
        return dict(_tax_cache[1])
    _tax_cache = (stamp, result)
    return dict(result)


def calculate_line(cost: float, margin: float, quantity: float = 1) -> dict[str, Any]:
    if not 0 <= margin < 1:
        raise ValueError(f"margin must be a fraction in [0, 1), got {margin}")
    # isfinite before the sign test: `nan < 0` is False, so a nan cost passed the
    # negative check and came back out as `sale_ea: nan, priced: True`, which
    # `compute_totals` then summed into grandTotal and `quote.persist` wrote to
    # Mongo. An inf cost was worse still - Decimal raises InvalidOperation, an
    # ArithmeticError, which the caller's `except (ValueError, TypeError)` did
    # not catch, so one bad row took down the whole quote screen.
    if not math.isfinite(cost):
        raise ValueError(f"cost must be a finite number, got {cost}")
    if cost < 0:
        raise ValueError(f"cost must not be negative, got {cost}")
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError(f"quantity must be a non-negative finite number, got {quantity}")
    divisor = 1 - margin
    exact_ea = Decimal(str(cost)) / Decimal(str(divisor))
    sale_ea = _money(exact_ea)
    # Round once, at the extension. Multiplying the already-rounded unit price
    # put up to half a cent of error into every unit: 74.33 at 27% over three
    # units extended to 305.46 where the arithmetic gives 305.47, and the error
    # scales linearly with quantity - so the printed extensions stopped
    # reconciling against a customer's own multiplication. `sale_ea` is still
    # the cents figure shown per unit; only the extension is computed exactly.
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
) -> dict[str, Any]:
    known = bands()
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
            "margin_check": validate_margin(product_type, margin),
        }
    )
    if override_margin is not None and not override_reason:
        result["warning"] = (
            "Margin overridden with no recorded reason - this is what the "
            "margin-governance flag exists for."
        )
    return result


def validate_margin(product_type: str, applied_margin: float) -> dict[str, Any]:
    floor = bands().get(product_type)
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
    """Roll-up price for one line; null sale_ea/ext_price count as unpriced (0)."""
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
    line_items: list[dict[str, Any]], project_state: str | None = None
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for item in line_items:
        group = str(item.get("group") or "ungrouped")
        ext = _line_ext_price(item)
        bucket = groups.setdefault(group, {"group": group, "line_count": 0, "subtotal": 0.0})
        bucket["line_count"] += 1
        bucket["subtotal"] = _money(bucket["subtotal"] + ext)

    subtotal = _money(sum(g["subtotal"] for g in groups.values()))
    state = normalise_state(project_state)
    tax_rate = tax_rates().get(state or "", 0.0)
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
    """Cost on the list x multiplier path, with adders applied where they belong.

    Adders go on the **list** price and the multiplier is applied to the sum -
    reference-library/adders/manual_adders.json says so outright: "These are LIST
    adders. Multiply by the same category multiplier as the base item to get
    cost." Adding one to the cost instead overcharges by the whole discount: a
    57.13 anti-microbial adder at Hager's 0.29 lock tier is 16.57 of cost, not
    57.13, so the wrong order inflates that line by roughly 40 dollars.

    Every adder is itemised in the result. An adder is a deliberate, recorded act
    - the price book never includes one in a lookup - so a line that carries one
    has to be able to show which, and for how much.
    """
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


def _ceil_to_grid(value: float, keys: list[int]) -> int | None:
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


def _lite_kit_data() -> dict[str, Any] | None:
    global _lite_kit_cache
    if _lite_kit_cache is not None:
        return _lite_kit_cache
    from cbc.services import reference_library as reflib

    try:
        _lite_kit_cache = reflib.load_lite_kit_prices()
    except Exception:
        return None
    return _lite_kit_cache


def lookup_lite_kit_list_price(
    width_in: float,
    height_in: float,
    pdf_page: int | None = None,
) -> dict[str, Any]:
    """NR-1: list price from lite_kit_prices for a width x height opening."""
    data = _lite_kit_data()
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
        height_key = _ceil_to_grid(height_in, sorted(int(h) for h in prices))
        width_key = _ceil_to_grid(width_in, widths)
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
