"""Tool definitions for the catalog MCP server.

These navigate. None of them returns a price, because none of them knows one -
the index says which page to open and the PDF says what things cost. That split
is the point: a number that reaches a quote was read off the sheet during that
run, not copied out of a table extracted months ago that may have misread it.
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_catalogs",
        "description": (
            "The vendor catalogs that are indexed, with page counts, effective "
            "dates, staleness and whether their prices are list or net. Start "
            "here when you do not know which book a vendor's parts are in."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Optional vendor key, e.g. 'hager'"}
            },
        },
    },
    {
        "name": "get_catalog_overview",
        "description": (
            "What one catalog is and how it is organised - product lines, how "
            "prices are shown, how to find a part, and the traps in it. Read this "
            "before hunting for a page in an unfamiliar book; it is a few hundred "
            "tokens and saves opening the wrong pages."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalog_id": {
                    "type": "string",
                    "description": "From list_catalogs, e.g. 'hager_price_book_18'",
                }
            },
            "required": ["catalog_id"],
        },
    },
    {
        "name": "find_pages",
        "description": (
            "Ranked catalog pages for a part number, series or description. "
            "Returns file_path and pdf_page — open with pdf-tools to read list prices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A part number, series or description: '3400 storeroom lock', 'BB1279', 'hand dryer'",
                },
                "vendor": {
                    "type": "string",
                    "description": "Optional vendor key. Narrow when you know it - a whole-library search is noisier.",
                },
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_page",
        "description": (
            "One page's index entry, for confirming a citation before it goes on "
            "a quote. Returns both page numbers, the description, the part "
            "families and how confident the index is about this page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalog_id": {"type": "string"},
                "pdf_page": {"type": "integer", "description": "1-indexed, as pdf-tools takes it"},
            },
            "required": ["catalog_id", "pdf_page"],
        },
    },
    {
        "name": "get_multiplier",
        "description": (
            "The CBC multiplier tier for a vendor, and product category where the "
            "vendor prices by category as Hager does, with its effective date. "
            "Curated by purchasing - never read off a PDF. Returns null with a "
            "note when the tier is unknown, never a guess."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "category": {
                    "type": "string",
                    "description": "Product category for vendors that price by category (Hager), e.g. 'locks', 'door_controls', 'exit_devices', 'architectural_hinges'",
                },
            },
            "required": ["vendor"],
        },
    },
    {
        "name": "get_special_net",
        "description": (
            "A fixed net price from a vendor's multiplier sheet, where one exists "
            "for this part. A special net is already the cost and overrides "
            "list x multiplier - do not multiply it again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"vendor": {"type": "string"}, "part_number": {"type": "string"}},
            "required": ["vendor", "part_number"],
        },
    },
    {
        "name": "is_stock_item",
        "description": (
            "Whether a part is on CBC's top-10 stock list for that vendor (NR-6). "
            "Beyond the stock list the manual cut-off applies and the estimator "
            "prices the line."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"vendor": {"type": "string"}, "part_number": {"type": "string"}},
            "required": ["vendor", "part_number"],
        },
    },
]
