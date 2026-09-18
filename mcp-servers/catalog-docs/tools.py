"""Tool definitions for the catalog-docs MCP server.

Read MinerU-parsed blocks for vendor price books and multiplier PDFs. Cropping
still goes through pdf-tools.get_page_image with a block's bbox — this server
never writes.
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_catalogs_parsed",
        "description": (
            "Price books / multiplier sheets with MinerU parse state and page "
            "counts. Prefer catalog-docs.search_blocks when parse_state is parsed; "
            "fall back to catalog.find_pages when parse is missing or failed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {
                    "type": "string",
                    "description": "Optional vendor filter (e.g. hager)",
                },
                "kind": {
                    "type": "string",
                    "description": "Optional: price_book | multiplier_sheet",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_outline",
        "description": (
            "Per-page outline for one catalog or multiplier sheet: title text and "
            "block counts. Use before search_blocks / get_page_blocks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalog_id": {
                    "type": "string",
                    "description": "pageIndex / catalogId stem, or sheetId for multipliers",
                },
                "price_book_id": {
                    "type": "string",
                    "description": "Mongo priceBooks _id (alternative to catalog_id)",
                },
                "source": {
                    "type": "string",
                    "description": "catalog (default) | multiplier",
                    "default": "catalog",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_blocks",
        "description": (
            "Full-text search over parsed catalog/multiplier blocks. Returns "
            "matching blocks with bbox, file_path, and pdf_page — crop with "
            "pdf-tools.get_page_image(region=bbox) only when a value is unclear. "
            "If no hits and parse is incomplete, use catalog.find_pages instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "catalog_id": {"type": "string"},
                "vendor": {"type": "string"},
                "source": {
                    "type": "string",
                    "description": "catalog | multiplier | both (default both)",
                    "default": "both",
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional block type filter, e.g. ['table','text']",
                },
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_page_blocks",
        "description": (
            "Blocks on one catalog/multiplier page, with a next cursor when "
            "truncated by max_chars. Prefer search_blocks when looking for a "
            "specific part or price."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalog_id": {"type": "string"},
                "price_book_id": {"type": "string"},
                "page": {"type": "integer", "description": "1-indexed page number"},
                "source": {
                    "type": "string",
                    "default": "catalog",
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "start": {"type": "integer", "default": 0},
                "max_chars": {"type": "integer", "default": 20000},
            },
            "required": ["page"],
        },
    },
]
