"""Tool definitions for the p21-connector MCP server.

READ-ONLY BY DESIGN. There is deliberately no create / update / delete tool here,
and there never will be in this workstream (NFR-5, .claude/rules/p21-read-only.md).
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_last_po",
        "description": (
            "Return the LAST purchase-order price for a part, with its PO date and "
            "freshness verdict. This is cost path 1. It never reads the P21 "
            "'supplier list' or 'supplier cost' fields - purchasing does not keep them "
            "current. When P21 is not connected this returns a structured "
            "'manual entry required' response, never a guessed price."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "part_number": {"type": "string", "description": "Manufacturer part number"},
                "vendor": {"type": "string"},
            },
            "required": ["part_number"],
        },
    },
    {
        "name": "check_freshness",
        "description": (
            "Apply the CBC freshness rule to a purchase date: under ~24 months is "
            "fresh, more than 24 months is unreliable, more than 2.5 years must "
            "be discarded."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "po_date": {"type": "string", "description": "ISO date, e.g. 2026-01-15"}
            },
            "required": ["po_date"],
        },
    },
    {
        "name": "search_item",
        "description": (
            "Search P21 for an item by description or part number. Exists mainly to "
            "surface the known mismatch risk: P21 item IDs frequently differ from "
            "manufacturer part numbers, and semi/custom items will not match at all."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
]
