"""Tool definitions for the reference MCP server (read-only)."""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_reference_families",
        "description": "List curated referenceData family ids (margins, tax, tiers, …).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_reference_document",
        "description": "Return the full data blob for one reference family.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "family": {
                    "type": "string",
                    "description": "e.g. margins, tax, vendor_tiers, lite_kit_prices",
                }
            },
            "required": ["family"],
        },
    },
    {
        "name": "get_margin_bands",
        "description": "Product-type margin bands and accessories rate.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_tax_rates",
        "description": "Nexus sales-tax rates by state code.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_finish_crosswalk",
        "description": "US / numeric finish crosswalk.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_frame_depth",
        "description": "Frame throat for a wall construction string.",
        "inputSchema": {
            "type": "object",
            "properties": {"wall_type": {"type": "string"}},
            "required": ["wall_type"],
        },
    },
    {
        "name": "get_frp_constants",
        "description": "FRP conversion constants (panel size, waste, trim, adhesive).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_manual_adders",
        "description": "Manual list adders (Hager and pending).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_special_customer_margin",
        "description": "Special margin for a named customer, if any.",
        "inputSchema": {
            "type": "object",
            "properties": {"customer": {"type": "string"}},
            "required": ["customer"],
        },
    },
    {
        "name": "get_vendor_tier",
        "description": "Vendor multiplier / category tiers from purchasing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["vendor"],
        },
    },
    {
        "name": "get_special_net",
        "description": "Hager special net price for a part, if on the sheet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "part": {"type": "string"},
            },
            "required": ["vendor", "part"],
        },
    },
    {
        "name": "lookup_lite_kit",
        "description": "NGP lite-kit list price for width x height (inches).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width_in": {"type": "number"},
                "height_in": {"type": "number"},
                "pdf_page": {"type": "integer"},
            },
            "required": ["width_in", "height_in"],
        },
    },
    {
        "name": "is_stock_item",
        "description": "Whether a part is on the vendor top-10 / stock list (NR-6).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "part": {"type": "string"},
            },
            "required": ["vendor", "part"],
        },
    },
    {
        "name": "get_custom_other_matrix",
        "description": "Custom / OTHER hardware-set matrix.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]
