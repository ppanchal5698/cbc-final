"""Running Claude Code on a pseudo-terminal and recording what it prints.

`subprocess.run(capture_output=True)` gives pipes, and a program on a pipe knows
it is not talking to a terminal: no progress rendering, no colour, and nothing at
all until the process exits. For a pass that runs for minutes over a 28-page bid
set, that means the estimator watches a spinner with no idea whether Claude is
reading sheet 3 or has been stuck on sheet 1 for ten minutes.

So the CLI gets a real pty here, and every byte it writes is appended to a
recording under `projects/{slug}/.runs/{job_id}.log`. The API tails that file to
the browser and xterm.js renders it - the same bytes, through a real terminal
emulator, rather than a summary of them.

The recording is bytes, not text: it carries the escape sequences that make it a
terminal session. It is capped, and credentials are stripped on the way in.
"""
from __future__ import annotations

from collections.abc import Callable
import errno
import os
import re
import select
import signal
import subprocess
import time
from pathlib import Path

# Enough to watch a long pass without letting one job fill the volume. A capped
# recording keeps its tail, because the end is where a failure explains itself.
MAX_RECORDING_BYTES = 4_000_000

# Patterns from cbc_core.secrets, applied to bytes as they stream.
_SECRET_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        rb"sk-ant-[A-Za-z0-9\-_]{16,}",
        rb"sk-or-[A-Za-z0-9\-_]{16,}",
        rb"sk-[A-Za-z0-9\-_]{24,}",
        rb"nvapi-[A-Za-z0-9\-_]{16,}",
        rb"ABSK[A-Za-z0-9+/=]{16,}",
        rb"\b(?:ASIA|AKIA)[A-Z0-9]{16}\b",
    )
]

# A credential can land across two reads, so the tail of each chunk is held back
# until the next one arrives and the pair can be scanned together.
_CARRY = 200


class Recorder:
    """Appends a redacted byte stream to a file, holding back split secrets."""

    def __init__(self, path: Path, extra_secrets: list[str] | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("wb")
        self._pending = b""
        self._written = 0
        self._extra = [s.encode("utf-8") for s in (extra_secrets or []) if len(s) >= 8]

    def _scrub(self, data: bytes) -> bytes:
        for secret in self._extra:
            data = data.replace(secret, b"[redacted]")
        for pattern in _SECRET_PATTERNS:
            data = pattern.sub(b"[redacted]", data)
        return data

    def feed(self, chunk: bytes) -> None:
        buffered = self._pending + chunk
        # Everything but the tail is safe to emit; the tail waits for its other half.
        emit, self._pending = buffered[:-_CARRY], buffered[-_CARRY:]
        if not emit:
            return
        self._write(self._scrub(emit))

    def _write(self, data: bytes) -> None:
        if self._written >= MAX_RECORDING_BYTES:
            return
        room = MAX_RECORDING_BYTES - self._written
        if len(data) > room:
            data = data[:room] + b"\r\n[recording truncated]\r\n"
        self._handle.write(data)
        self._handle.flush()
        self._written += len(data)

    def close(self) -> None:
        if self._pending:
            self._write(self._scrub(self._pending))
            self._pending = b""
        try:
            self._handle.close()
        except OSError:
            pass


def run_on_pty(
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    timeout: int,
    recording: Path,
    redact_values: list[str] | None = None,
    columns: int = 120,
    rows: int = 40,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[int, str]:
    """Run a command on a pty, recording it live. Returns (exit code, plain text).

    The plain text is what the existing job log and the auth-marker checks read;
    the recording is what the browser renders.
    """
    import pty

    controller, follower = pty.openpty()
    try:
        import fcntl
        import struct
        import termios

        fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    except (ImportError, OSError):
        pass

    child_env = dict(env or os.environ)
    child_env.setdefault("TERM", "xterm-256color")
    # Ink renders progress only when it believes a human is watching, which on a
    # pty it now does. This is the whole point of the exercise.
    child_env.pop("CI", None)

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=follower,
        stdout=follower,
        stderr=follower,
        env=child_env,
        close_fds=True,
        start_new_session=True,
    )
    os.close(follower)

    recorder = Recorder(recording, redact_values)
    collected = bytearray()
    deadline = time.time() + timeout
    timed_out = False
    cancelled = False

    try:
        while True:
            if cancel_check and cancel_check():
                cancelled = True
                _terminate(process)
                break
            if time.time() > deadline:
                timed_out = True
                _terminate(process)
                break
            try:
                readable, _, _ = select.select([controller], [], [], 1.0)
            except OSError:
                break
            if not readable:
                if process.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(controller, 65536)
            except OSError as exc:
                # EIO is how a pty reports that the child closed its end.
                if exc.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            recorder.feed(chunk)
            if len(collected) < MAX_RECORDING_BYTES:
                collected.extend(chunk)
    finally:
        recorder.close()
        try:
            os.close(controller)
        except OSError:
            pass

    returncode = process.poll()
    if returncode is None:
        _terminate(process)
        returncode = process.poll() if process.poll() is not None else -1
    if timed_out:
        returncode = 124
    if cancelled:
        returncode = 130

    return returncode, collected.decode("utf-8", errors="replace")


def _terminate(process: subprocess.Popen) -> None:
    """Kill the whole process group - the CLI spawns MCP servers as children."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            pass


def recording_path(
    project_slug: str | None,
    job_id: str,
    root: Path,
    attempt: int = 1,
) -> Path:
    """Where a job's terminal recording lives.

    Under the project so it travels with the bid and is visible to both
    containers through the same shared volume; jobs with no project get a shared
    folder rather than being dropped.

    Retries get their own file so a second Claude pass does not look like an
    unexplained second session appended to the first attempt's log.
    """
    base = root / (f"projects/{project_slug}" if project_slug else "projects/_system")
    if attempt <= 1:
        name = f"{job_id}.log"
    else:
        name = f"{job_id}-attempt{attempt}.log"
    return base / ".runs" / name


def write_retry_banner(recording: Path, attempt: int) -> None:
    """Mark the start of a re-queued attempt in the byte recording."""
    recording.parent.mkdir(parents=True, exist_ok=True)
    banner = f"\r\n=== RETRY attempt {attempt} ===\r\n".encode("utf-8")
    with recording.open("wb") as handle:
        handle.write(banner)


def summarise(raw: str) -> tuple[str, str]:
    """Reduce a stream-json session to (final text, error text).

    The rest of the worker was written against `--print`, whose stdout is just
    the answer. Streaming changes stdout to a JSON event per line, so the answer
    has to be lifted back out - otherwise the job log would hold the transcript
    and the auth-marker check would scan JSON instead of the message it needs to
    find.
    """
    import json

    final: list[str] = []
    errors: list[str] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        kind = event.get("type")
        if kind == "result":
            if event.get("is_error"):
                errors.append(str(event.get("result") or event.get("error") or "")[:2000])
            elif event.get("result"):
                final.append(str(event["result"]))
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    final.append(block["text"])
        elif kind == "system" and event.get("subtype") == "error":
            errors.append(str(event.get("message") or "")[:2000])

    # The last result event is the answer; earlier assistant text is working out
    # loud and only matters when nothing final arrived.
    return (final[-1] if final else raw[-4000:]), "\n".join(errors)


def recording_warnings(raw: str) -> list[str]:
    """Surface provider issues visible in a stream-json recording."""
    warnings: list[str] = []
    # unrecognized_model is expected for Ollama/@cf wire IDs; provider.describe
    # already explains the overlay / window-enforcement handling. Do not
    # double-alarm the estimator from the stream alone.
    if "InputValidationError" in raw and "description" in raw and "Agent" in raw:
        warnings.append(
            "Agent tool calls failed validation (missing description). "
            "Check worker prompt Agent-tool schema."
        )
    return warnings
