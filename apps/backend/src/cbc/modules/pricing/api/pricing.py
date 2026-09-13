"""Quote arithmetic - a thin adapter over the calc-engine MCP server.

There is exactly one implementation of the money math in this system and it is
`cbc_core/calc.py`. This module adapts it to API shapes; it does not reimplement
any of it. If you find yourself writing `cost / (1 - margin)` here, stop.

The calc-engine MCP server is an adapter over the same module, so a price a run
computes and a price this API computes cannot drift.
"""
from __future__ import annotations

from typing import Any

from cbc.core import calc

# Division prefix -> margin band. The estimator can override per line; this is
# only the default the band framework applies (.claude/memory/margin_sheet.md).
DIVISION_BANDS = {
    "08 11": "commodity",
    "08 14": "specialty",
    "08 71": "commodity",
    "10 21": "restroom_partitions",
    "10 28": "accessories",
    "06 64": "specialty",
}
DEFAULT_BAND = "commodity"


def band_for_division(division: str | None) -> str:
    if not division:
        return DEFAULT_BAND
    key = division.strip()[:5]
    return DIVISION_BANDS.get(key, DEFAULT_BAND)


def default_margin(division: str | None) -> float:
    bands = calc.bands()
    return bands.get(band_for_division(division), bands[DEFAULT_BAND])


def price_line(
    cost: float | None,
    margin: float | None,
    qty: float,
    division: str | None = None,
) -> dict[str, Any]:
    """Compute sell and extended for one line.

    An unpriced line (cost is None) stays unpriced - it is a manual or
    awaiting-quote item and must not be silently valued at zero.
    """
    if cost is None:
        return {"sell": None, "extended": None, "margin": margin, "priced": False}
    if qty is None:
        # `float(qty or 0)` used to turn a stored null into 0, so the line came
        # back `extended: 0.0, priced: True` - not counted in unpricedLines
        # (cost is not None), carrying no priceError, and rolling the bid up
        # short by the whole line. A quantity we do not have is unpriced (NFR-2).
        return {
            "sell": None,
            "extended": None,
            "margin": margin,
            "priced": False,
            "error": "quantity is missing",
        }

    applied = default_margin(division) if margin is None else float(margin)
    try:
        line = calc.calculate_line(cost=float(cost), margin=applied, quantity=float(qty))
    except (ArithmeticError, ValueError, TypeError) as exc:
        # Schema bounds stop new bad values; this catches the ones already stored
        # and anything a pipeline run wrote straight into Mongo. An unpriceable
        # line is reported as unpriced, not raised - the caller is looping over
        # every line on the bid, and one of them must not take the screen down.
        return {
            "sell": None,
            "extended": None,
            "margin": margin,
            "priced": False,
            "error": str(exc),
        }
    return {
        "sell": line["sale_ea"],
        "extended": line["ext_price"],
        "margin": applied,
        "divisor": line["divisor"],
        "priced": True,
    }


def check_margin(division: str | None, margin: float | None) -> dict[str, Any]:
    if margin is None:
        return {"status": "unpriced"}
    return calc.validate_margin(band_for_division(division), float(margin))


def totals(lines: list[dict[str, Any]], state: str | None, freight: float | None = None) -> dict:
    """Roll priced lines up into group subtotals, tax and a grand total."""
    payload = [
        {
            "group": line.get("division") or "Other",
            "ext_price": line.get("extended") or 0,
        }
        for line in lines
    ]
    # NONE is an explicit "no nexus" ruling, not a missing value.
    explicit_none = state == "NONE"
    result = calc.compute_totals(payload, project_state=None if explicit_none else state)
    if explicit_none:
        result["project_state"] = "NONE"
        result["tax_note"] = "No nexus - the estimator has ruled this bid untaxed."

    if freight:
        result["freight"] = round(float(freight), 2)
        result["freightNote"] = "Freight quoted on this bid"
        result["grand_total"] = round(result["grand_total"] + float(freight), 2)

    blended = None
    costed = [line for line in lines if line.get("cost") is not None]
    total_cost = sum(float(line["cost"]) * float(line.get("qty") or 0) for line in costed)
    total_sell = sum(float(line.get("extended") or 0) for line in costed)
    if total_sell:
        blended = round((total_sell - total_cost) / total_sell, 4)

    return {
        "subtotal": result["subtotal"],
        "margin": blended,
        "cost": round(total_cost, 2),
        "taxRate": result["tax_rate"],
        "tax": result["tax"],
        "freight": result.get("freight"),
        "freightNote": result.get("freightNote") or result["freight_note"],
        "grandTotal": result["grand_total"],
        "taxJurisdiction": result["project_state"],
        "taxNote": result["tax_note"],
        "groups": result["groups"],
        "unpricedLines": sum(1 for line in lines if line.get("cost") is None),
    }
