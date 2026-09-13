#!/usr/bin/env python3
"""PostToolUse: validate extraction/pricing output after it is written.

Scope checkpoint files and door_schedule **block** (exit 2) when schema-invalid
so the next subagent does not run on garbage. Other extraction/pricing checks
warn only (exit 0) — the worker's post-session gate is the hard backstop.
Rule: .claude/rules/accuracy-trust.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _artifact_path import project_path_from_tool

ROOT = Path(__file__).resolve().parents[2]

# Exit 2 = Claude Code PostToolUse block (do not continue as if the write succeeded).
BLOCK = 2

SCHEMA_PATHS = frozenset(
    {
        "extracted/scope_metadata.json",
        "extracted/scope_summary.json",
        "extracted/door_schedule.json",
    }
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


def _schema_problems(project: str, rel_path: str) -> list[str]:
    path = ROOT / "projects" / project / rel_path
    if not path.is_file():
        return [f"{project}: {rel_path} missing after write"]
    try:
        from cbc.modules.extraction.api.artifact_schema import validate_artifact_text
    except ImportError:
        # Fallback without packages on path: JSON object check only.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return [f"{project}: {rel_path} is not valid JSON ({exc})"]
        if rel_path.endswith("scope_summary.json"):
            if not isinstance(data, dict) or "frp_in_scope" not in data:
                return [f"{project}: scope_summary.json missing frp_in_scope"]
        return []
    return [
        f"{project}: {msg}" for msg in validate_artifact_text(rel_path, path.read_text(encoding="utf-8"))
    ]


def check(payload: dict) -> int:
    tool_input = payload.get("tool_input") or {}
    resolved = project_path_from_tool(payload.get("tool_name"), tool_input)
    if not resolved:
        return 0

    project, rel_path = resolved
    rel = rel_path.replace("\\", "/")

    if rel in SCHEMA_PATHS:
        problems = _schema_problems(project, rel)
        for problem in problems:
            print(f"ERROR {problem}", file=sys.stderr)
        return BLOCK if problems else 0

    try:
        from cbc.validation import check_extraction, check_pricing
    except ImportError:
        return 0

    if rel.startswith("extracted/"):
        problems, warnings = check_extraction(project)
    elif rel.startswith("priced/"):
        problems, warnings = check_pricing(project, require_hardware_sets=True)
    else:
        return 0

    for warning in warnings:
        print(f"WARN  {warning}", file=sys.stderr)
    for problem in problems:
        print(f"ERROR {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
