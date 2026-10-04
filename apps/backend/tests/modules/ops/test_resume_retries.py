"""A retry picks its own session up instead of starting the pass over.

Every attempt was a brand-new conversation, so a retry re-read the sheets,
rebuilt the schedule and rediscovered whatever broke. Across the recorded runs
on this repo that came to **$14.24 over 269 turns** in eight cold retries - one
take-off retry alone was $6.53 for 74 turns, against a first attempt that had
already done most of the work.

Resuming is deliberately scoped to the *same leg of the same job*. Carrying a
session across domain jobs was measured and loses: the take-off leg's
conversation sits at ~146k tokens per turn, so handing it to pricing adds about
$1.17 of cache reads to a job that costs $1.87 - to save the three or four turns
pricing spends reading artifacts. The phases talk through files on disk, which is
what makes them cheap to start cold and expensive to carry.
"""
from __future__ import annotations

import pytest

from cbc.modules.ops.api import claude_cli, claude_pass


def _job(attempts: int, legs: list[dict] | None = None) -> dict:
    return {"_id": "j1", "type": "extract_bid_set", "attempts": attempts, "waveLegs": legs or []}


def test_a_first_attempt_resumes_nothing() -> None:
    legs = [{"label": "takeoff", "ok": False, "sessionId": "abc-123"}]
    assert claude_pass.sessions_from(_job(1, legs)) == {}


def test_a_retry_resumes_the_leg_that_recorded_the_session() -> None:
    legs = [
        {"label": "takeoff", "ok": False, "sessionId": "abc-123"},
        {"label": "frp", "ok": True, "sessionId": "def-456"},
        {"label": "div10", "ok": False, "sessionId": None},
    ]
    found = claude_pass.sessions_from(_job(2, legs))

    assert found["takeoff"] == "abc-123"
    assert "div10" not in found, "a leg with no recorded session resumes nothing"


def test_a_single_pass_job_records_under_the_empty_label() -> None:
    """match_and_price has no wave, so its retry is a cold start over the whole job."""
    legs = [{"label": "", "ok": False, "sessionId": "solo-1"}]
    assert claude_pass.sessions_from(_job(2, legs)) == {"": "solo-1"}


def test_resume_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setattr(claude_pass, "RESUME_RETRIES", False)
    legs = [{"label": "takeoff", "ok": False, "sessionId": "abc-123"}]
    assert claude_pass.sessions_from(_job(2, legs)) == {}


def test_the_session_id_is_read_off_the_stream() -> None:
    raw = (
        '{"type":"system","subtype":"init","session_id":"9f8e7d6c-1111-2222-3333-444455556666"}\n'
        '{"type":"result","session_id":"9f8e7d6c-1111-2222-3333-444455556666","num_turns":3}\n'
    )
    assert claude_cli.session_id_from_stream(raw) == "9f8e7d6c-1111-2222-3333-444455556666"


def test_a_killed_run_still_yields_its_session() -> None:
    """The run a retry most wants to resume is the one that never reached a result."""
    raw = '{"type":"system","subtype":"init","session_id":"aaaa-bbbb-cccc-dddd"}\n'
    assert claude_cli.session_id_from_stream(raw) == "aaaa-bbbb-cccc-dddd"
    assert claude_cli.session_id_from_stream("") is None
    # The id is opaque and handed straight back to --resume, so no shape is assumed.
    assert claude_cli.session_id_from_stream('{"session_id":"s-9"}') == "s-9"


@pytest.mark.parametrize(
    "text",
    ["No conversation found with session ID abc", "Error: session not found"],
)
def test_a_missing_session_is_recognised_so_the_pass_can_fall_back(text: str) -> None:
    """Failing here would cost the whole job - strictly worse than never resuming."""
    outcome = claude_cli.RunResult(ok=False, output="", error=text, returncode=1)
    assert claude_pass._session_gone(outcome) is True


def test_an_ordinary_failure_is_not_mistaken_for_a_missing_session() -> None:
    outcome = claude_cli.RunResult(ok=False, output="", error="rate limited", returncode=1)
    assert claude_pass._session_gone(outcome) is False


def test_the_flag_reaches_the_cli(monkeypatch, tmp_path) -> None:
    """Plumbing that never reaches argv is plumbing that does nothing."""
    from cbc.modules.ops.infrastructure import streaming

    seen: dict = {}

    def fake_pty(command, **kwargs):
        seen["command"] = command
        return 0, '{"type":"result","session_id":"s-9","num_turns":1,"total_cost_usd":0}'

    monkeypatch.setattr(claude_cli, "resolve_binary", lambda: "claude")
    monkeypatch.setattr(streaming, "run_on_pty", fake_pty)

    result = claude_cli.run_claude(
        "do the thing",
        recording=tmp_path / "r.log",
        resume_session_id="s-9",
        cwd=tmp_path,
    )

    command = seen["command"]
    assert "--resume" in command, command
    assert command[command.index("--resume") + 1] == "s-9"
    assert result.session_id == "s-9", "the session must come back for the next retry"


def test_no_resume_flag_when_there_is_nothing_to_resume(monkeypatch, tmp_path) -> None:
    from cbc.modules.ops.infrastructure import streaming

    seen: dict = {}
    monkeypatch.setattr(claude_cli, "resolve_binary", lambda: "claude")
    monkeypatch.setattr(
        streaming, "run_on_pty",
        lambda command, **kw: (seen.update(command=command), (0, '{"type":"result"}'))[1],
    )

    claude_cli.run_claude("do the thing", recording=tmp_path / "r.log", cwd=tmp_path)

    assert "--resume" not in seen["command"]
