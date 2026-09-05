#!/usr/bin/env python3
"""Development check that every registered CBC MCP server comes up.

    python mcp-servers/main.py --selftest   # every server imports and lists its tools

In production Claude Code starts each server itself, from the registration in
`.mcp.json` at the repo root (an `mcpServers` block in the project settings file
is ignored). This script reads that same file rather than keeping its own list:
the hand-maintained copy said "five servers", listed six, and omitted
`document-index` entirely - so the newest server was the one CI never checked.

Servers implementing a `_demo()` are additionally run with `--demo`, which
exercises them against real data rather than only asserting that they start.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MCP_CONFIG = ROOT / ".mcp.json"


def registered_servers() -> list[str]:
    """Server names from .mcp.json, in registration order."""
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    return list(config.get("mcpServers", {}))


def _server_script(name: str) -> Path:
    return HERE / name / "server.py"


def _has_demo(name: str) -> bool:
    script = _server_script(name)
    return script.exists() and "def _demo(" in script.read_text(encoding="utf-8")


def _run(name: str, flag: str) -> bool:
    result = subprocess.run(
        [sys.executable, str(_server_script(name)), flag],
        capture_output=True,
        text=True,
    )
    print((result.stdout or result.stderr).strip())
    return result.returncode == 0


def selftest() -> int:
    servers = registered_servers()
    missing = [n for n in servers if not _server_script(n).exists()]
    if missing:
        print(f"FAILED: registered in .mcp.json but no server.py: {missing}")
        return 1

    failures = [n for n in servers if not _run(n, "--selftest")]
    failures += [f"{n} (demo)" for n in servers if _has_demo(n) and not _run(n, "--demo")]

    if failures:
        print(f"\nFAILED: {failures}")
        return 1
    print(f"\nAll {len(servers)} MCP servers OK.")
    return 0


if __name__ == "__main__":
    if "--selftest" not in sys.argv:
        print(__doc__)
        sys.exit(2)
    sys.exit(selftest())
