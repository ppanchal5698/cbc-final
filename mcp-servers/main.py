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


def _run(name: str, flag: str) -> tuple[bool, bool]:
    """(ok, skipped). A server that skips its demo exits 0 and proves nothing."""
    result = subprocess.run(
        [sys.executable, str(_server_script(name)), flag],
        capture_output=True,
        text=True,
    )
    output = (result.stdout or result.stderr).strip()
    print(output)
    return result.returncode == 0, "SKIPPED" in output


def selftest() -> int:
    servers = registered_servers()
    missing = [n for n in servers if not _server_script(n).exists()]
    if missing:
        print(f"FAILED: registered in .mcp.json but no server.py: {missing}")
        return 1

    failures = [n for n in servers if not _run(n, "--selftest")[0]]

    skipped: list[str] = []
    for name in servers:
        if not _has_demo(name):
            continue
        ok, was_skipped = _run(name, "--demo")
        if not ok:
            failures.append(f"{name} (demo)")
        elif was_skipped:
            skipped.append(name)

    if failures:
        print(f"\nFAILED: {failures}")
        return 1

    # A skipped demo exits 0, so it used to be counted as a pass and the summary
    # claimed every server was checked. bid-docs, catalog and catalog-docs skip
    # without a read-only credential, which is most of the time - so the line
    # said "All 8 OK" while three of them had touched no data at all.
    if skipped:
        print(
            f"\n{len(servers)} MCP servers start; {len(skipped)} demo(s) not run: "
            f"{', '.join(skipped)}."
        )
        print(
            "  Those read MongoDB with a credential that cannot write. Set "
            "MONGODB_READONLY_URI, or start the stack so one can be derived, to "
            "exercise them."
        )
        return 0

    print(f"\nAll {len(servers)} MCP servers OK.")
    return 0


if __name__ == "__main__":
    if "--selftest" not in sys.argv:
        print(__doc__)
        sys.exit(2)
    sys.exit(selftest())
