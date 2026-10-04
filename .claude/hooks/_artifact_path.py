"""Resolve project-relative paths from Write/Edit or artifact-storage MCP calls."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_FILE_RE = re.compile(r"projects/([^/\"\\]+)/(.+?)(?:\"|$|\\)")

# The tools that write a project file. project_path_from_tool also recognises a
# path inside a Bash command, which the audit log wants - but validating or
# formatting after a `cat` acted on reads as if they were writes.
_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


def slashes(text: str) -> str:
    return text.replace("\\\\", "/").replace("\\", "/")


def writes_artifact(tool_name: str | None) -> bool:
    name = tool_name or ""
    return name in _WRITE_TOOLS or "save_artifact" in name or "propose_patch" in name


def bid_dir(project: str) -> Path | None:
    """The bid's working directory, from the roots the delete guard trusts.

    The PostToolUse hooks built `<repo>/projects/<bid>`, which has not existed
    since bids moved under `data/projects`. The audit log then wrote nothing and
    the validator reported every save as "missing after write". _projects_roots
    has the precedence that matches storage_root(): a sandbox's clone first, then
    STORAGE_ROOT, then the checkout's data/projects.
    """
    from pre_delete_guard import _projects_roots

    for root in _projects_roots():
        candidate = root / project
        if candidate.is_dir():
            return candidate
    return None


def project_path_from_tool(tool_name: str | None, tool_input: dict[str, Any]) -> tuple[str, str] | None:
    """Return (project_slug, relative_path) when the call writes a project file."""
    if not tool_input:
        return None

    if tool_name and ("save_artifact" in tool_name or "propose_patch" in tool_name):
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
