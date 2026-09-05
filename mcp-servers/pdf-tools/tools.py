"""Tool definitions for the pdf-tools MCP server.

Every tool that reads a PDF returns source_page on each result (NFR-3 auditability).
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_sheets",
        "description": (
            "Page map: which sheets mention which terms, ranked. Start a take-off "
            "here - it answers 'which sheets matter?' in one call instead of one "
            "search per term, and returns counts rather than page text."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF file"},
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Terms to look for. Omit for the Division 8/10 defaults "
                        "(door schedule, frame, hardware, partition, FRP, ...)."
                    ),
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "extract_text",
        "description": (
            "Extract text from a PDF, page by page, with 1-indexed page numbers for "
            "auditability. Falls back to OCR only if a page has no extractable text. "
            "Repairs glyph-coded fonts and reports it as encoding_repaired."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF file"},
                "pages": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional 1-indexed page numbers. Omit for all pages.",
                },
                "max_pages": {
                    "type": "integer",
                    "default": 4,
                    "description": "Cap on pages read in one call (default 4).",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "extract_tables",
        "description": (
            "Extract schedule-like tables from a PDF. Architectural sheets are CAD "
            "drawings whose 'tables' have no reliable ruling, so this clusters "
            "positioned words into rows and columns rather than trusting line "
            "detection. Returns rows with source_page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "page_range": {
                    "type": "string",
                    "description": "e.g. '1-30', '14', or 'all' (default)",
                },
                "region": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional [x0, y0, x1, y1] clip in PDF points",
                },
                "max_pages": {
                    "type": "integer",
                    "default": 4,
                    "description": "Cap on pages read in one call (default 4).",
                },
                "include_cell_boxes": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include per-cell bboxes. Default true.",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "get_page_image",
        "description": (
            "Render one PDF page to a PNG image for visual drawing take-off. "
            "Writes the PNG to .cache/pdf-pages (or out_dir) and returns its path. "
            "Full-page renders clamp the long edge to 1568 px; a region crop may exceed that."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "page_number": {"type": "integer", "description": "1-indexed"},
                "dpi": {"type": "integer", "default": 200},
                "out_dir": {"type": "string", "description": "Optional output directory"},
                "region": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional [x0, y0, x1, y1] clip in PDF points",
                },
            },
            "required": ["file_path", "page_number"],
        },
    },
    {
        "name": "get_page_size",
        "description": (
            "Page dimensions in PDF points. Every bbox returned by extract_tables is "
            "measured against these, so a viewer needs them to scale a highlight."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "page_number": {"type": "integer", "description": "1-indexed"},
            },
            "required": ["file_path", "page_number"],
        },
    },
    {
        "name": "search_pdf",
        "description": (
            "Case-insensitive keyword search across a PDF. Returns every hit with its "
            "1-indexed source_page and surrounding context - the fastest way to locate "
            "a DOOR SCHEDULE, HARDWARE GROUPS, or a Division 10 section."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "query": {"type": "string"},
                "context_chars": {"type": "integer", "default": 160},
                "max_hits": {"type": "integer", "default": 40},
            },
            "required": ["file_path", "query"],
        },
    },
]
