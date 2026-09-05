"""Resolve project-relative paths from Write/Edit or artifact-storage MCP calls."""
from __future__ import annotations

import json
import re
from typing import Any

PROJECT_FILE_RE = re.compile(r"projects/([^/\"\\]+)/(.+?)(?:\"|$|\\)")


def slashes(text: str) -> str:
    return text.replace("\\\\", "/").replace("\\", "/")


def project_path_from_tool(tool_name: str | None, tool_input: dict[str, Any]) -> tuple[str, str] | None:
    """Return (project_slug, relative_path) when the call writes a project file."""
    if not tool_input:
        return None

    if tool_name and "save_artifact" in tool_name:
        project = tool_input.get("project")
        path = tool_input.get("path")
        if project and path:
            return str(project), slashes(str(path))
        return None

    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path:
        blob = slashes(json.dumps(tool_input, default=str))
        match = PROJECT_FILE_RE.search(blob)
        if match:
            return match.group(1), match.group(2)
        return None

    normalized = slashes(str(file_path))
    match = PROJECT_FILE_RE.search(normalized)
    if match:
        return match.group(1), match.group(2)
    return None
