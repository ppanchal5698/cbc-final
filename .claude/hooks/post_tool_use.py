#!/usr/bin/env python3
"""Single PostToolUse process: validate, then format, then audit.

Audit always runs. Scope-checkpoint validation may return exit 2 to block the
pipeline when scope_metadata / scope_summary is invalid mid-chain.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


HOOKS = Path(__file__).resolve().parent

# Hooks run as standalone scripts under the system interpreter, so the backend
# package is not importable unless it happens to be pip-installed. Without this
# the tool_session guard below is silently skipped.
_BACKEND_SRC = HOOKS.parent.parent / "apps" / "backend" / "src"
if _BACKEND_SRC.is_dir() and str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))


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


# Shared path helper first - log_audit_trail imports it by bare name.
_exec("_artifact_path")
log_audit_trail = _exec("log_audit_trail")
post_extraction_validate = _exec("post_extraction_validate")
post_quote_format = _exec("post_quote_format")


def check(payload: dict) -> int:
    # Audit first (NFR-3). Then validation may block on bad scope checkpoints.
    try:
        log_audit_trail.check(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"hook log_audit_trail failed: {exc}", file=sys.stderr)

    # Release orchestrator lock when a subagent finishes writing its outputs.
    try:
        tool = str(payload.get("tool_name") or "")
        if tool in {
            "mcp__artifact-storage__save_artifact",
            "Write",
            "Agent",
        }:
            from cbc.worker_kit import tool_session

            inp = payload.get("tool_input") or {}
            inp = inp if isinstance(inp, dict) else {}
            if tool == "Agent":
                # Release this subagent only. Take-off, FRP and Div 10 run
                # concurrently; clearing every lock when the first one returns
                # unlocked files the other two were still writing.
                tool_session.clear_active_agent(
                    str(inp.get("subagent_type") or inp.get("agent") or "") or None
                )
            else:
                written = str(
                    inp.get("path") or inp.get("file_path") or inp.get("rel_path") or ""
                )
                if written and tool_session._state_path().is_file():
                    tool_session.clear_active_agent(rel_path=written.replace("\\", "/"))
    except Exception as exc:  # noqa: BLE001
        print(f"hook tool_session clear skipped: {exc}", file=sys.stderr)

    block = 0
    try:
        block = int(post_extraction_validate.check(payload) or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"hook post_extraction_validate failed: {exc}", file=sys.stderr)

    try:
        post_quote_format.check(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"hook post_quote_format failed: {exc}", file=sys.stderr)

    return block


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


if __name__ == "__main__":
    sys.exit(main())
