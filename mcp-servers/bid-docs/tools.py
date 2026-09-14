"""Tool definitions for the bid-docs MCP server.

Read MinerU-parsed blocks for uploaded bid PDFs. Cropping still goes through
pdf-tools.get_page_image with a block's bbox — this server never writes.
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_documents",
        "description": (
            "Documents on a bid (by project code or slug), with parse state and "
            "page counts. Start here to see which PDFs have MinerU blocks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Bid code (e.g. CBC-260001) or project slug",
                }
            },
            "required": ["project"],
        },
    },
    {
        "name": "get_outline",
        "description": (
            "Per-page outline for one document: sheet number or title text and "
            "block counts. Use before search_blocks / get_page_blocks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "document_id": {
                    "type": "string",
                    "description": "Mongo document id from list_documents",
                },
            },
            "required": ["project", "document_id"],
        },
    },
    {
        "name": "search_blocks",
        "description": (
            "Full-text search over parsed blocks. Returns matching blocks with "
            "bbox and page_size — crop with pdf-tools.get_page_image(region=bbox) "
            "only when a value is unclear."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "query": {"type": "string"},
                "document_id": {"type": "string"},
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional block type filter, e.g. ['table','text']",
                },
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["project", "query"],
        },
    },
    {
        "name": "get_page_blocks",
        "description": (
            "Blocks on one page, with a next cursor when truncated by max_chars. "
            "Prefer search_blocks when looking for a specific value."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "document_id": {"type": "string"},
                "page": {"type": "integer", "description": "1-indexed page number"},
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "start": {"type": "integer", "default": 0},
                "max_chars": {"type": "integer", "default": 20000},
            },
            "required": ["project", "document_id", "page"],
        },
    },
]
