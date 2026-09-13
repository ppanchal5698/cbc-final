"""Recording a process's terminal session as it runs.

The estimator watches a pass that takes minutes. Buffered pipes give nothing
until it exits, and a summary of the output hides the thing you open a terminal
to see - which sheet it is on, and whether it is still moving.

These cover the three properties that make the recording worth having: it grows
while the process runs, it keeps the escape sequences that make it a terminal
session, and it never carries a credential.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from tests.shared import ROOT  # noqa: E402

from cbc.core import streaming  # noqa: E402

posix_only = pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")


@posix_only
def test_the_recording_grows_while_the_process_is_still_running(tmp_path):
    """A file that only appears at the end is no better than a buffered pipe."""
    recording = tmp_path / "run.log"
    seen: list[int] = []

    def watch() -> None:
        for _ in range(14):
            seen.append(recording.stat().st_size if recording.exists() else 0)
            time.sleep(0.25)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()

    code, _ = streaming.run_on_pty(
        ["bash", "-c", "for i in 1 2 3; do echo step $i; sleep 0.6; done"],
        cwd=ROOT,
        env=None,
        timeout=30,
        recording=recording,
    )
    watcher.join(timeout=5)

    assert code == 0
    assert len(set(seen)) > 1, f"never grew mid-run: {seen}"


@posix_only
def test_escape_sequences_survive(tmp_path):
    """Stripping these would leave a log, not a terminal session."""
    recording = tmp_path / "run.log"
    streaming.run_on_pty(
        ["bash", "-c", r"printf '\033[32mgreen\033[0m\n'"],
        cwd=ROOT,
        env=None,
        timeout=20,
        recording=recording,
    )

    raw = recording.read_bytes()
    assert b"\x1b[32m" in raw
    assert b"green" in raw


@posix_only
def test_a_credential_never_reaches_the_recording(tmp_path):
    """The browser renders this file, so it is a place secrets must not appear."""
    recording = tmp_path / "run.log"
    token = "sk-ant-oat01-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"

    streaming.run_on_pty(
        ["bash", "-c", f"echo using {token} now"],
        cwd=ROOT,
        env=None,
        timeout=20,
        recording=recording,
        redact_values=[token],
    )

    raw = recording.read_bytes()
    assert token.encode() not in raw
    assert b"[redacted]" in raw


@posix_only
def test_a_credential_split_across_two_reads_is_still_caught(tmp_path):
    """Redacting each chunk on its own misses a secret that straddles them."""
    recording = tmp_path / "run.log"
    recorder = streaming.Recorder(recording)
    token = "sk-ant-api03-" + "x" * 40

    half = len(token) // 2
    recorder.feed(b"prefix " + token[:half].encode())
    recorder.feed(token[half:].encode() + b" suffix")
    recorder.close()

    raw = recording.read_bytes()
    assert token.encode() not in raw
    assert b"[redacted]" in raw


@posix_only
def test_a_runaway_process_is_stopped_at_the_timeout(tmp_path):
    """A job that never ends must not hold the worker forever."""
    recording = tmp_path / "run.log"
    started = time.time()

    code, _ = streaming.run_on_pty(
        ["bash", "-c", "while true; do echo tick; sleep 0.2; done"],
        cwd=ROOT,
        env=None,
        timeout=3,
        recording=recording,
    )

    assert code == 124
    assert time.time() - started < 25


def test_the_recording_lives_under_the_bid_it_belongs_to():
    """So it travels with the project and both containers see the same file."""
    path = streaming.recording_path("dutch_bros_macarthur_2026", "abc123", ROOT)

    assert path.parent.name == ".runs"
    assert "dutch_bros_macarthur_2026" in str(path)
    assert path.name == "abc123.log"


def test_a_job_with_no_project_still_gets_a_home():
    """Dropping the recording would be worse than filing it somewhere shared."""
    path = streaming.recording_path(None, "xyz789", ROOT)

    assert path.name == "xyz789.log"
    assert "_system" in str(path)


def test_retries_get_their_own_recording_file():
    path = streaming.recording_path("test_bid", "abc123", ROOT, attempt=2)

    assert path.name == "abc123-attempt2.log"


def test_retry_banner_marks_a_fresh_attempt(tmp_path):
    recording = tmp_path / "job.log"
    streaming.write_retry_banner(recording, 2)

    assert b"=== RETRY attempt 2 ===" in recording.read_bytes()
