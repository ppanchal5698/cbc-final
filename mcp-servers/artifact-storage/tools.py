"""Tool definitions for the artifact-storage MCP server."""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "save_artifact",
        "description": (
            "Write a file inside projects/{project}/ and keep a SHA-256 versioned copy "
            "so a later run can be compared against an earlier one. Refuses any path "
            "that escapes the project directory (.claude/rules/file-safety.md)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project directory name"},
                "path": {
                    "type": "string",
                    "description": "Path relative to the project, e.g. extracted/door_schedule.json",
                },
                "content": {"type": "string"},
                "version_note": {"type": "string", "description": "Optional label for this version"},
            },
            "required": ["project", "path", "content"],
        },
    },
    {
        "name": "propose_patch",
        "description": (
            "Change named fields of an artifact that already exists. Prefer this over "
            "save_artifact for extracted/* checkpoints: the deterministic seed is the "
            "base, each patch is validated on its own, and a patch that fails costs "
            "that one field and leaves a review flag instead of failing the whole write. "
            "Every patch that fills a value must cite the page it was read from "
            "(.claude/rules/pdf-verify-before-present.md)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "path": {
                    "type": "string",
                    "description": "e.g. extracted/door_schedule.json - must already exist",
                },
                "patches": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["set", "append"]},
                            "path": {
                                "type": "string",
                                "description": (
                                    "openings/<door number>/<field>, e.g. openings/05/handing. "
                                    "The door number, never a list index."
                                ),
                            },
                            "value": {},
                            "evidence": {
                                "type": "object",
                                "properties": {
                                    "source_page": {"type": "integer"},
                                    "excerpt": {"type": "string"},
                                    "bbox": {"type": "array", "items": {"type": "number"}},
                                },
                                "required": ["source_page", "excerpt"],
                            },
                        },
                        "required": ["path", "value"],
                    },
                },
                "version_note": {"type": "string"},
            },
            "required": ["project", "path", "patches"],
        },
    },
    {
        "name": "get_artifact",
        "description": (
            "Read an artifact, either the live file or a specific stored version hash. "
            "Returns at most max_chars characters with total_chars and next; when next "
            "is set the reply is a slice, not the whole file - continue from it rather "
            "than parsing what you have as complete JSON."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "path": {"type": "string"},
                "version": {"type": "string", "description": "Optional SHA-256 prefix"},
                "start": {"type": "integer", "default": 0, "description": "Character offset to read from"},
                "max_chars": {
                    "type": "integer",
                    "default": 20000,
                    "description": "Characters per call (ceiling 200000)",
                },
            },
            "required": ["project", "path"],
        },
    },
    {
        "name": "list_versions",
        "description": "List every stored version of one artifact, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["project", "path"],
        },
    },
    {
        "name": "list_project_files",
        "description": "List everything currently in a project directory, with sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "subdir": {"type": "string", "description": "Optional subdirectory filter"},
            },
            "required": ["project"],
        },
    },
]
