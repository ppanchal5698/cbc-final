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
        "name": "get_artifact",
        "description": "Read an artifact, either the live file or a specific stored version hash.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "path": {"type": "string"},
                "version": {"type": "string", "description": "Optional SHA-256 prefix"},
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
