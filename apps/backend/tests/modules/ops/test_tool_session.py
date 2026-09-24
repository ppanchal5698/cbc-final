"""tool_session warns on duplicate reads and never blocks.

Docstring history (the behaviour this file used to assert, now deleted):

    Subagent path locks must survive take-off, FRP and Div 10 running together.
    The lock held a single `active_agent` / `active_paths` pair. Once wave 3
    started launching its three take-offs in one message, the third launch
    overwrote the first two, and the first subagent to finish released everyone's
    files - so the guard was silently off for exactly the run shape it protects.

That guard is gone (W2a). `_tool_path` only ever resolved Read and get_artifact,
never a write, so it blocked the harmless case; and the lock was written on the
orchestrator's Agent call against a state file shared across the sandbox, so the
subagent's own first `get_artifact("extracted/line_items.json")` - the call
every prompt orders it to make first - matched its own lock and stalled for the
120s TTL. Single-writer safety lives in pre_delete_guard's checkpoint rules and
in disjoint wave outputs; only the token-saving read hint remains here.
"""
from __future__ import annotations

import json

import pytest

from cbc.worker_kit import tool_session


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    yield tmp_path


def _launch(agent: str) -> int:
    return tool_session.check({"tool_name": "Agent", "tool_input": {"subagent_type": agent}})


def _read(rel: str) -> int:
    return tool_session.check(
        {"tool_name": "Read", "tool_input": {"file_path": f"projects/demo/{rel}"}}
    )


def _get_artifact(rel: str) -> int:
    return tool_session.check(
        {"tool_name": "mcp__artifact-storage__get_artifact", "tool_input": {"path": rel}}
    )


def test_an_agent_launch_no_longer_locks_any_path(session) -> None:
    for agent in ("takeoff-engineer", "frp-specialist", "div10-specialist"):
        assert _launch(agent) == 0
    # The former owner check is gone: the path a running Agent used to "own" reads fine.
    assert _read("extracted/line_items.json") == 0


def test_a_subagent_can_read_its_own_first_artifact(session) -> None:
    """The self-collision the old guard caused: the orchestrator's Agent call
    wrote a lock the subagent's own opening get_artifact then tripped."""
    assert _launch("takeoff-engineer") == 0
    assert _get_artifact("extracted/line_items.json") == 0


def test_every_read_is_allowed(session) -> None:
    for rel in (
        "extracted/line_items.json",
        "review/review_flags.json",
        "priced/line_items.json",
        "extracted/scope_metadata.json",
    ):
        assert _read(rel) == 0


def test_a_duplicate_read_warns_but_allows(session, capsys) -> None:
    assert _read("extracted/line_items.json") == 0
    capsys.readouterr()
    assert _read("extracted/line_items.json") == 0
    err = capsys.readouterr().err
    assert "was already read" in err


def test_the_state_file_is_valid_json_after_a_save(session) -> None:
    _read("extracted/line_items.json")
    state_path = tool_session._state_path()
    assert state_path.is_file()
    # Atomic write leaves a whole, parseable file and no stray temp beside it.
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "reads" in data
    assert "active" not in data
    leftovers = list(state_path.parent.glob(f".{tool_session._STATE_NAME}.*.tmp"))
    assert leftovers == []
