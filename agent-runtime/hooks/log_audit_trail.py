#!/usr/bin/env python3
"""PostToolUse: append one JSONL record per tool call (NFR-3).

Always exits 0 - logging never blocks the pipeline.
Rule: .claude/rules/auditability.md
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _artifact_path import project_path_from_tool

PROJECT_RE = re.compile(r"projects/([^/\"]+)/")
ROOT = Path(__file__).resolve().parents[2]
MAX_SUMMARY = 300
SESSION_LOG = ROOT / "claude.log"


def slashes(text: str) -> str:
    """Normalise both real and JSON-escaped Windows separators to '/'."""
    return text.replace("\\\\", "/").replace("\\", "/")


def summarise(tool_name: str | None, tool_input: dict) -> str:
    resolved = project_path_from_tool(tool_name, tool_input)
    if resolved:
        project, rel_path = resolved
        return f"project={project} path={rel_path}"[:MAX_SUMMARY]
    for key in ("file_path", "command", "query", "part_number", "path"):
        if key in tool_input:
            return f"{key}={str(tool_input[key])[:MAX_SUMMARY]}"
    return json.dumps(tool_input, default=str)[:MAX_SUMMARY]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


def check(payload: dict) -> int:
    tool_input = payload.get("tool_input") or {}
    tool_name = payload.get("tool_name")
    resolved = project_path_from_tool(tool_name, tool_input)
    if resolved:
        project = resolved[0]
    else:
        match = PROJECT_RE.search(slashes(json.dumps(tool_input, default=str)))
        project = match.group(1) if match else "_unassigned"

    log_dir = ROOT / "projects" / project
    if not log_dir.is_dir():
        return 0

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "tool_input_summary": summarise(tool_name, tool_input),
        "agent_name": payload.get("agent_name") or payload.get("subagent_type") or "orchestrator",
        "session_id": payload.get("session_id"),
    }
    line = json.dumps(record)
    with (log_dir / "audit_trail.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    # Mirror hook activity into the session log for post-mortems (plan: hooks visibility).
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    hook_line = f"[{stamp}] HOOK audit {tool_name or 'tool'} {record['tool_input_summary']}\n"
    try:
        with SESSION_LOG.open("a", encoding="utf-8") as session_log:
            session_log.write(hook_line)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
