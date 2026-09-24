"""PreToolUse: warn on duplicate reads within a run.

This once also enforced single-writer isolation between concurrent subagents, but
that guard blocked the harmless case (`_tool_path` only ever resolved Read and
get_artifact, never a write) and self-collided (the subagent's own first
get_artifact matched the lock the orchestrator had written for it, stalling it for
the 120s TTL). Single-writer safety is enforced by things that work -
`pre_delete_guard`'s checkpoint rules and the disjoint wave outputs promoted with
nothing to reconcile - so the blocking is gone; only the token-saving read hint
remains.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

# Session file lives under the Claude project dir (scratch workspace) when set.
_STATE_NAME = ".cbc_tool_session.json"


def _state_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CBC_PROJECTS_ROOT") or "."
    return Path(root) / _STATE_NAME


def _empty() -> dict[str, Any]:
    return {"reads": {}}


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("reads", {})
    return data


def _save(data: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: three wave processes share this file. A plain
        # truncate-and-write can tear; os.replace() rename cannot. A lost update
        # to this warning cache costs one missing "already read" hint, not data.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{_STATE_NAME}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data))
            os.replace(tmp, path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        pass


def _tool_path(payload: dict) -> str | None:
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return None
    if tool in {"Read", "mcp__artifact-storage__get_artifact"}:
        for key in ("file_path", "path", "rel_path", "relative_path"):
            raw = inp.get(key)
            if raw:
                text = str(raw).replace("\\", "/")
                # Normalize to project-relative when possible.
                for marker in ("/projects/", "projects/"):
                    if marker in text:
                        text = text.split(marker, 1)[1]
                        parts = text.split("/", 1)
                        if len(parts) == 2:
                            return parts[1]
                return text.lstrip("/")
    return None


def check(payload: dict) -> int:
    """Warn on a duplicate read within 60s. Always returns 0 - never blocks.

    The subagent-isolation block this used to carry is gone: it blocked reads
    (never writes) and self-collided on the subagent's own first get_artifact.
    """
    import sys

    rel = _tool_path(payload)
    if not rel:
        return 0

    state = _load()
    now = time.time()

    # Duplicate read within 60s of the same path → warn but allow (agent may need it).
    reads = state.get("reads") or {}
    prior = reads.get(rel)
    if isinstance(prior, dict):
        age = now - float(prior.get("at") or 0)
        if age < 60:
            print(
                f"WARN: `{rel}` was already read {age:.0f}s ago — reuse that result "
                "instead of re-fetching (saves tokens).",
                file=sys.stderr,
            )

    reads[rel] = {"at": now}
    # Bound growth.
    if len(reads) > 200:
        oldest = sorted(reads.items(), key=lambda kv: float((kv[1] or {}).get("at") or 0))
        for key, _ in oldest[:50]:
            reads.pop(key, None)
    state["reads"] = reads
    _save(state)
    return 0
