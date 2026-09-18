#!/usr/bin/env python3
"""Single PreToolUse process: send-quote guard, then delete/write guard.

Exit 2 = block the tool call. Exit 0 = allow.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


HOOKS = Path(__file__).resolve().parent


def _exec(name: str) -> ModuleType:
    path = HOOKS / f"{name}.py"
    mod_name = f"cbc_hook_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load shared helpers before the guards that import them.
_exec("_artifact_path")
pre_delete_guard = _exec("pre_delete_guard")
pre_send_quote = _exec("pre_send_quote")


def check(payload: dict) -> int:
    blocked = pre_send_quote.check(payload)
    if blocked:
        return blocked
    # Orchestrator / duplicate-read guard (warn or block).
    try:
        from cbc.worker_kit import tool_session

        blocked = tool_session.check(payload)
        if blocked:
            return blocked
    except Exception as exc:  # never fail a tool call because the guard broke
        print(f"WARN: tool_session guard skipped: {exc}", file=sys.stderr)
    return pre_delete_guard.check(payload)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


if __name__ == "__main__":
    sys.exit(main())
