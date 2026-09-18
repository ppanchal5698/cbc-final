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
terminal session. Tool results are compacted, it is capped, and credentials are
stripped on the way in.
"""
from __future__ import annotations

from collections.abc import Callable
import errno
import json
import os
import re
import select
import signal
import subprocess
import time
from pathlib import Path

# Enough to watch a long pass without letting one job fill the volume.
MAX_RECORDING_BYTES = 4_000_000
# Past the cap, what a run did still lands - agent text, errors, the final result
# with its cost - up to this; the result itself always does.
_HARD_CAP = MAX_RECORDING_BYTES * 2
# How much of one tool result's text the recording keeps.
RESULT_KEEP_CHARS = 4_000
# A "line" this long with no newline is not an event stream; stop holding it.
_MAX_LINE = 32_000_000

_ESSENTIAL = frozenset(
    {"assistant", "result", "rate_limit_event", "system/init", "system/error", "system/api_retry"}
)
_TRIMMED_MARKER = (
    b"\r\n[recording trimmed: tool results past the size cap are not kept - the run "
    b"continues, and its messages and final result still are]\r\n"
)

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

def _compact_content(content: object) -> tuple[object, int]:
    """A tool result's content with image data and long text left out, and how much was."""
    if isinstance(content, str):
        if len(content) <= RESULT_KEEP_CHARS:
            return content, 0
        return content[:RESULT_KEEP_CHARS], len(content) - RESULT_KEEP_CHARS
    if not isinstance(content, list):
        return content, 0
    omitted = 0
    parts: list[object] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image":
            source = part.get("source")
            data = source.get("data") if isinstance(source, dict) else None
            if isinstance(data, str) and data:
                omitted += len(data)
                part = {**part, "source": {**source, "data": ""}}
        elif isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            if len(part["text"]) > RESULT_KEEP_CHARS:
                omitted += len(part["text"]) - RESULT_KEEP_CHARS
                part = {**part, "text": part["text"][:RESULT_KEEP_CHARS]}
        parts.append(part)
    return parts, omitted


def compact_line(line: bytes) -> bytes:
    """Shrink the tool results in one stream-json line before it is recorded.

    A page image read into context arrives as ~500 KB of base64 in a `user` event.
    On a real bid, 63 tool results were 89% of a 4 MB recording, which then stopped
    at the cap while the run went on for minutes - no log, and no final result, so
    runMetrics never learned what the run cost. The terminal and runMetrics need
    the fact of a result and its size, not its pixels: an image keeps its block with
    the data emptied, long text keeps its head, and `omitted_chars` says how much
    was left out.
    """
    if len(line) <= RESULT_KEEP_CHARS:
        return line
    start, end = line.find(b"{"), line.rfind(b"}")
    if start < 0 or end < start:
        return line
    try:
        event = json.loads(line[start : end + 1])
    except ValueError:
        return line
    if not isinstance(event, dict) or event.get("type") != "user":
        return line
    changed = False
    message = event.get("message")
    blocks = message.get("content") if isinstance(message, dict) else None
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        content, omitted = _compact_content(block.get("content"))
        if omitted:
            block["content"] = content
            block["omitted_chars"] = int(block.get("omitted_chars") or 0) + omitted
            changed = True
    extra = event.get("tool_use_result")
    if extra is not None:
        size = len(json.dumps(extra, default=str))
        if size > RESULT_KEEP_CHARS:
            event["tool_use_result"] = {"omitted_chars": size}
            changed = True
    if not changed:
        return line
    compacted = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return line[:start] + compacted + line[end + 1 :]


def _event_kind(line: bytes) -> str | None:
    """`result`, `assistant`, `system/init`... for a recorded line; None if it is not an event."""
    start, end = line.find(b"{"), line.rfind(b"}")
    if start < 0 or end < start:
        return None
    try:
        event = json.loads(line[start : end + 1])
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    kind = str(event.get("type") or "")
    return f"{kind}/{event.get('subtype')}" if kind == "system" else kind


class Recorder:
    """Appends a compacted, redacted stream-json session to a file, a line at a time.

    Whole lines are held until their newline arrives, so a credential split across
    two reads is scrubbed as one string and each event can be compacted as JSON.
    """

    def __init__(self, path: Path, extra_secrets: list[str] | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("wb")
        self._line = b""
        self._written = 0
        self._trimmed = False
        self._extra = [s.encode("utf-8") for s in (extra_secrets or []) if len(s) >= 8]

    def _scrub(self, data: bytes) -> bytes:
        for secret in self._extra:
            data = data.replace(secret, b"[redacted]")
        for pattern in _SECRET_PATTERNS:
            data = pattern.sub(b"[redacted]", data)
        return data

    def feed(self, chunk: bytes) -> bytes:
        """Record `chunk`. Returns the bytes actually kept - compacted and redacted."""
        kept = bytearray()
        self._line += chunk
        while (newline := self._line.find(b"\n")) >= 0:
            line, self._line = self._line[: newline + 1], self._line[newline + 1 :]
            kept += self._write(self._scrub(compact_line(line)))
        if len(self._line) > _MAX_LINE:
            line, self._line = self._line, b""
            kept += self._write(self._scrub(line))
        return bytes(kept)

    def _write(self, data: bytes) -> bytes:
        if not data:
            return b""
        if self._written + len(data) > MAX_RECORDING_BYTES:
            kind = _event_kind(data)
            keep = kind == "result" or (
                kind in _ESSENTIAL and self._written + len(data) <= _HARD_CAP
            )
            if not keep:
                if self._trimmed:
                    return b""
                self._trimmed = True
                data = _TRIMMED_MARKER
        self._handle.write(data)
        self._handle.flush()
        self._written += len(data)
        return data

    def close(self) -> bytes:
        """Flush an unfinished last line. Returns the bytes it kept."""
        tail = b""
        if self._line:
            tail = self._write(self._scrub(compact_line(self._line)))
            self._line = b""
        try:
            self._handle.close()
        except OSError:
            pass
        return tail


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
            # What the worker reads back is what was recorded: the same compacted
            # events, so the final result is in it however long the run went on.
            collected.extend(recorder.feed(chunk))
    finally:
        collected.extend(recorder.close())
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
    label: str | None = None,
) -> Path:
    """Where a job's terminal recording lives.

    Under the project so it travels with the bid and is visible to both
    containers through the same shared volume; jobs with no project get a shared
    folder rather than being dropped.

    Retries get their own file so a second Claude pass does not look like an
    unexplained second session appended to the first attempt's log.
    """
    base = root / (f"projects/{project_slug}" if project_slug else "projects/_system")
    # Concurrent passes in one job each get their own file, for the same reason
    # retries do: three sessions interleaved into one log is not a recording of
    # anything, and the estimator watches these.
    stem = f"{job_id}-{label}" if label else job_id
    if attempt <= 1:
        name = f"{stem}.log"
    else:
        name = f"{stem}-attempt{attempt}.log"
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
