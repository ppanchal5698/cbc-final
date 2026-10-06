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

from _artifact_path import bid_dir, project_path_from_tool, slashes

PROJECT_RE = re.compile(r"projects/([^/\"]+)/")
ROOT = Path(__file__).resolve().parents[2]
MAX_SUMMARY = 300
SESSION_LOG = ROOT / "claude.log"


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

    log_dir = bid_dir(project)
    if log_dir is None:
        return 0

    # Claude Code names the subagent in `agent_type` (and `agent_id`); the main
    # session sends neither. This read `agent_name` / `subagent_type`, which no
    # payload carries - `subagent_type` is only an Agent call's input - so every
    # line said "orchestrator". Keys checked against a captured payload, CLI 2.1.289.
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "tool_input_summary": summarise(tool_name, tool_input),
        "agent_name": payload.get("agent_type") or "orchestrator",
        "agent_id": payload.get("agent_id"),
        "session_id": payload.get("session_id"),
        "tool_use_id": payload.get("tool_use_id"),
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
