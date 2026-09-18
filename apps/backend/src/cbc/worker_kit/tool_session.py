"""PreToolUse: reduce duplicate reads and enforce subagent isolation."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Session file lives under the Claude project dir (scratch workspace) when set.
_STATE_NAME = ".cbc_tool_session.json"
_DELEGATION_PATHS = {
    "product-matcher": (
        "extracted/hardware_sets.json",
        "extracted/door_schedule.json",
        "extracted/scope_summary.json",
    ),
    "pricing-engineer": (
        "priced/line_items.json",
        "priced/margin_applied.json",
        "extracted/hardware_sets.json",
    ),
    "quality-reviewer": ("review/review_flags.json",),
    "delivery-agent": (
        "review/quotation_email_draft.md",
        "quotation.html",
    ),
    "takeoff-engineer": ("extracted/door_schedule.json",),
    "spec-scope-analyst": (
        "extracted/scope_metadata.json",
        "extracted/scope_summary.json",
    ),
}


def _state_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CBC_PROJECTS_ROOT") or "."
    return Path(root) / _STATE_NAME


def _empty() -> dict[str, Any]:
    # `active` is a dict of agent -> {"paths": [...], "at": epoch}. It was a single
    # `active_agent` / `active_paths` pair, which silently lost every lock but the
    # last one as soon as take-off, FRP and Div 10 started launching together.
    return {"reads": {}, "active": {}}


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
    active = data.get("active")
    if not isinstance(active, dict):
        active = {}
    # Carry a pre-existing single-slot lock over rather than dropping it.
    legacy_agent = data.pop("active_agent", None)
    legacy_paths = data.pop("active_paths", None)
    if legacy_agent and legacy_paths:
        active.setdefault(
            str(legacy_agent),
            {"paths": [str(p) for p in legacy_paths], "at": float(data.get("active_at") or 0)},
        )
    data["active"] = active
    return data


def _save(data: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
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
    """Return 2 to block, 0 to allow. Prints WARN/ERROR to stderr."""
    import sys

    tool = str(payload.get("tool_name") or "")
    state = _load()
    now = time.time()

    # Track Agent launches so the orchestrator cannot race the subagent's files.
    if tool == "Agent":
        inp = payload.get("tool_input") or {}
        sub = ""
        if isinstance(inp, dict):
            sub = str(inp.get("subagent_type") or inp.get("agent") or "")
        paths = list(_DELEGATION_PATHS.get(sub, ()))
        # One entry per concurrent subagent. Take-off, FRP and Div 10 launch in
        # the same message, and a single slot meant the third launch erased the
        # first two locks.
        state["active"][sub or "unknown"] = {"paths": paths, "at": now}
        _save(state)
        return 0

    rel = _tool_path(payload)
    if not rel:
        return 0

    # Soft-complete: expire each lock on its own clock, so a long take-off does
    # not keep FRP's stale entry alive and a short one does not release it early.
    active = state.get("active") or {}
    fresh = {
        name: entry
        for name, entry in active.items()
        if isinstance(entry, dict) and now - float(entry.get("at") or 0) <= 120
    }
    if len(fresh) != len(active):
        state["active"] = fresh
        _save(state)
        active = fresh

    owner = _owner_of(rel, active)
    if owner:
        print(
            f"ERROR: Do not duplicate subagent work — `{owner}` owns `{rel}`. "
            "Wait for its completion notification before reading that path.",
            file=sys.stderr,
        )
        return 2

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


def _owner_of(rel: str, active: dict[str, Any]) -> str | None:
    """Which running subagent owns this path, if any."""
    for name, entry in (active or {}).items():
        paths = [str(p) for p in (entry or {}).get("paths") or []]
        if any(rel == p or rel.endswith(p) for p in paths):
            return name
    return None


def clear_active_agent(agent: str | None = None, *, rel_path: str | None = None) -> None:
    """Release one subagent's lock, or all of them when nothing identifies one.

    Releasing everything on any subagent's completion is what made concurrency
    unsafe: take-off finishing would unlock the files FRP and Div 10 were still
    writing. A save identifies its owner by the path written; an Agent result
    identifies it by name.
    """
    state = _load()
    active = state.get("active") or {}
    if not active:
        return
    if agent and agent in active:
        active.pop(agent, None)
    elif rel_path:
        owner = _owner_of(rel_path, active)
        if owner is None:
            return  # a write nobody claimed releases nothing
        active.pop(owner, None)
    else:
        active.clear()
    state["active"] = active
    _save(state)
