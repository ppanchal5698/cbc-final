#!/usr/bin/env python3
"""PostToolUse: tidy quotation.html after it is written. Never blocks."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from _artifact_path import project_path_from_tool

ROOT = Path(__file__).resolve().parents[2]


def _target_path(payload: dict) -> Path | None:
    tool_input = payload.get("tool_input") or {}
    resolved = project_path_from_tool(payload.get("tool_name"), tool_input)
    if resolved:
        project, rel_path = resolved
        if rel_path.endswith("quotation.html"):
            return ROOT / "projects" / project / rel_path
        return None

    path = str(tool_input.get("file_path") or "")
    if path.endswith("quotation.html"):
        return Path(path)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


def check(payload: dict) -> int:
    target = _target_path(payload)
    if target is None or not target.is_file():
        return 0

    path = str(target)
    if shutil.which("prettier"):
        subprocess.run(["prettier", "--write", "--parser", "html", path], capture_output=True)
        return 0

    try:
        import pyhtmlbeautifier  # noqa: F401
    except ImportError:
        return 0
    subprocess.run([sys.executable, "-m", "pyhtmlbeautifier", path], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
