"""Subagent path locks must survive take-off, FRP and Div 10 running together.

The lock held a single `active_agent` / `active_paths` pair. Once wave 3 started
launching its three take-offs in one message, the third launch overwrote the
first two, and the first subagent to finish released everyone's files - so the
guard was silently off for exactly the run shape it exists to protect.
"""
from __future__ import annotations

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


def test_three_concurrent_launches_each_keep_their_lock(session) -> None:
    for agent in ("takeoff-engineer", "frp-specialist", "div10-specialist"):
        assert _launch(agent) == 0

    # take-off still owns the door schedule even though two agents launched after it
    assert _read("extracted/door_schedule.json") == 2


def test_one_subagent_finishing_does_not_unlock_the_others(session) -> None:
    _launch("takeoff-engineer")
    _launch("product-matcher")

    tool_session.clear_active_agent("product-matcher")

    assert _read("extracted/door_schedule.json") == 2, "take-off is still running"


def test_a_finished_subagent_releases_its_own_paths(session) -> None:
    _launch("takeoff-engineer")
    assert _read("extracted/door_schedule.json") == 2

    tool_session.clear_active_agent("takeoff-engineer")
    assert _read("extracted/door_schedule.json") == 0


def test_a_save_releases_the_agent_that_owns_the_written_path(session) -> None:
    _launch("takeoff-engineer")
    _launch("quality-reviewer")

    tool_session.clear_active_agent(rel_path="extracted/door_schedule.json")

    assert _read("extracted/door_schedule.json") == 0, "its owner just wrote it"
    assert _read("review/review_flags.json") == 2, "the reviewer is still running"


def test_a_write_nobody_claimed_releases_nothing(session) -> None:
    _launch("takeoff-engineer")
    tool_session.clear_active_agent(rel_path="extracted/some_other_file.json")
    assert _read("extracted/door_schedule.json") == 2


def test_an_unclaimed_path_is_always_readable(session) -> None:
    _launch("takeoff-engineer")
    assert _read("extracted/scope_metadata.json") == 0


def test_a_stale_lock_expires_on_its_own_clock(session, monkeypatch) -> None:
    """A long take-off must not keep a short FRP's entry alive, or vice versa."""
    _launch("takeoff-engineer")

    real_time = tool_session.time.time
    monkeypatch.setattr(tool_session.time, "time", lambda: real_time() + 300)
    assert _read("extracted/door_schedule.json") == 0
