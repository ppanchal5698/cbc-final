"""Tool definitions for the calc-engine MCP server.

Pure computation. This server owns the only money math in the system:
    Sale $ EA = Cost / (1 - margin)
    Ext       = Sale $ EA x Qty
"""
from __future__ import annotations

from typing import Any

PRODUCT_TYPES = [
    "commodity",
    "restroom_partitions",
    "specialty",
    "custom_built",
    "accessories",
]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "cost_from_list",
        "description": (
            "List price x multiplier cost with adders on the list first. "
            "See price-line-item skill for adder order."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "list_price": {"type": "number", "description": "The list figure read off the page"},
                "multiplier": {"type": "number", "description": "The vendor tier, e.g. 0.29"},
                "adders": {
                    "type": "array",
                    "description": "Optional. Each {name, list_adder} from reference-library.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "list_adder": {"type": "number"},
                        },
                    },
                },
            },
            "required": ["list_price", "multiplier"],
        },
    },
    {
        "name": "lookup_lite_kit_list_price",
        "description": (
            "NR-1 lite-kit list price for width x height from lite_kit_prices.json. "
            "Apply vendor multiplier separately via cost_from_list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "width_in": {"type": "number", "description": "Opening width in inches"},
                "height_in": {"type": "number", "description": "Opening height in inches"},
                "pdf_page": {
                    "type": "integer",
                    "description": "Optional vendor table page (e.g. 30 for NGP)",
                },
            },
            "required": ["width_in", "height_in"],
        },
    },
    {
        "name": "calculate_line",
        "description": (
            "Compute one quote line from cost, margin and quantity. "
            "Returns sale_ea, ext_price and the arithmetic used, rounded to cents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cost": {"type": "number", "description": "Our Cost, per each"},
                "margin": {
                    "type": "number",
                    "description": "Margin as a fraction, e.g. 0.27 for the commodity band",
                },
                "quantity": {"type": "number", "default": 1},
            },
            "required": ["cost", "margin"],
        },
    },
    {
        "name": "apply_margin",
        "description": (
            "Look up the default margin band for a product type and apply it to a cost. "
            "The band is an editable default - pass override_margin with a reason when "
            "sourcing changes it (Wendy's, distributor-bought lines, custom first builds)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cost": {"type": "number"},
                "product_type": {"type": "string", "enum": PRODUCT_TYPES},
                "override_margin": {"type": "number"},
                "override_reason": {"type": "string"},
            },
            "required": ["cost", "product_type"],
        },
    },
    {
        "name": "compute_totals",
        "description": (
            "Roll a list of priced lines up into per-group subtotals and a grand total, "
            "grouped by door with accessories and FRP kept as separate blocks. "
            "Adds sales tax only for Ohio and Kentucky."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "line_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "group": {"type": "string"},
                            "sale_ea": {"type": "number"},
                            "quantity": {"type": "number"},
                            "ext_price": {"type": "number"},
                        },
                    },
                },
                "project_state": {
                    "type": "string",
                    "description": "Two-letter ship-to state. Tax applies only to OH and KY.",
                },
            },
            "required": ["line_items"],
        },
    },
    {
        "name": "validate_margin",
        "description": (
            "Check an applied margin against the floor for its product type. "
            "Returns pass/fail - it flags, it never blocks (NFR-8 is deferred)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product_type": {"type": "string", "enum": PRODUCT_TYPES},
                "applied_margin": {"type": "number"},
            },
            "required": ["product_type", "applied_margin"],
        },
    },
]
