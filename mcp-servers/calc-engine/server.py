#!/usr/bin/env python3
"""calc-engine MCP server - the arithmetic behind every quote, over stdio.

The arithmetic itself lives in `cbc_core/calc.py`, because the API prices lines
too and there must be exactly one implementation of it. This file is the adapter
that exposes it as MCP tools; it holds no formulas of its own.
"""
from __future__ import annotations

from _runtime import serve
from tools import TOOLS

from cbc.modules.pricing.api.calc import (
    apply_margin,
    calculate_line,
    compute_totals,
    cost_from_list,
    lookup_lite_kit_list_price,
    validate_margin,
)

HANDLERS = {
    "calculate_line": calculate_line,
    "cost_from_list": cost_from_list,
    "lookup_lite_kit_list_price": lookup_lite_kit_list_price,
    "apply_margin": apply_margin,
    "compute_totals": compute_totals,
    "validate_margin": validate_margin,
}


def _demo() -> None:
    """Runnable check: the arithmetic that every quote depends on."""
    line = calculate_line(cost=74.33, margin=0.27, quantity=3)
    assert line["sale_ea"] == 101.82, line
    # 74.33 / 0.73 = 101.8219..., times three is 305.4657 -> 305.47. The 305.46
    # this used to assert came from multiplying the rounded 101.82, which is
    # half a cent per unit adrift and pinned the defect in place with its own
    # test. Rounding happens once, at the extension.
    assert line["ext_price"] == 305.47, line

    totals = compute_totals(
        [
            {"group": "Door 01", "ext_price": 305.46},
            {"group": "Door 01", "sale_ea": 100.0, "quantity": 2},
            {"group": "Accessories", "ext_price": 50.0},
        ],
        project_state="OH",
    )
    assert totals["subtotal"] == 555.46, totals
    assert totals["tax"] == 44.44, totals
    assert totals["grand_total"] == 599.90, totals

    untaxed = compute_totals([{"group": "g", "ext_price": 100.0}], project_state="LA")
    assert untaxed["tax"] == 0.0 and untaxed["grand_total"] == 100.0, untaxed

    assert validate_margin("commodity", 0.20)["status"] == "fail"
    assert validate_margin("commodity", 0.27)["status"] == "pass"
    print("calc-engine demo OK")


if __name__ == "__main__":
    serve("calc-engine", TOOLS, HANDLERS, demo=_demo)
