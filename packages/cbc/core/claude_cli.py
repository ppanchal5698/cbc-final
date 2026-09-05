"""Invoking Claude Code headless.

One place in the system spawns `claude --print`. It lives below both `api` and
`worker` because both of them need it: the worker to run a job, and the settings
screen to test a provider before it becomes the one every job uses. It captures the log, enforces a
timeout, and reports failure honestly rather than pretending a job succeeded.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import threading

from cbc.core import secrets
from cbc.core.paths import repo_root

REPO_ROOT = repo_root()

MAX_LOG_CHARS = 20_000


class HeartbeatWatchdog:
    """Ping `callback` every `interval` seconds until stop(). Daemon thread.

    Lives next to the Claude subprocess so a blocked asyncio loop cannot starve
    the job's Mongo heartbeat (the fencing token the reaper watches).
    """

    def __init__(self, callback: Callable[[], None] | None, interval: float) -> None:
        self._callback = callback
        self._interval = max(0.1, float(interval or 30))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._callback is None:
            return
        self._thread = threading.Thread(
            target=self._run, name="claude-heartbeat", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._callback()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def resolve_binary() -> str | None:
    """Find the Claude Code CLI.

    On Windows npm installs it as claude.cmd, which subprocess will not resolve
    from a bare name - shutil.which honours PATHEXT and finds it.
    """
    configured = os.environ.get("CLAUDE_BIN", "claude")
    if Path(configured).is_file():
        return configured
    found = shutil.which(configured)
    if found:
        return found
    for suffix in (".cmd", ".exe", ".ps1"):
        found = shutil.which(configured + suffix)
        if found:
            return found
    return None


@dataclass
class RunResult:
    ok: bool
    output: str
    error: str | None
    returncode: int
    # A failure that retrying cannot fix. A missing CLI and a rejected credential
    # are the same on the third attempt as on the first, and burning the attempt
    # budget on them only delays the error the estimator needs to read.
    permanent: bool = False
    error_code: str | None = None


def _settings_argv(settings: dict[str, Any] | None) -> list[str]:
    if not settings:
        return []
    return ["--settings", json.dumps(settings, separators=(",", ":"))]


def run_claude(
    prompt: str,
    timeout: int = 1800,
    env: dict[str, str] | None = None,
    redact_values: list[str] | None = None,
    recording: "Path | None" = None,
    job_type: str | None = None,
    max_turns: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    settings: dict[str, Any] | None = None,
    *,
    bare: bool = False,
    system_prompt: str | None = None,
    on_heartbeat: Callable[[], None] | None = None,
    heartbeat_seconds: float = 30,
    cwd: Path | None = None,
) -> RunResult:
    """Run one headless Claude Code pass in the repo root.

    --dangerously-skip-permissions is used because an unattended run cannot
    answer prompts. The safety comes from the PreToolUse hooks, which fire
    regardless of permission mode and block every send and destructive delete.

    `env` comes from `api.services.provider.build_env`, so which provider serves
    a job is a configured choice rather than a property of the shell that
    happened to launch the worker. Passing None inherits the environment, which
    is what preflight from a terminal wants.

    `settings` is merged via `claude --settings` (user/managed-scope keys such as
    modelPicker.behavesAs). Project `.claude/settings.json` cannot carry those.

    `bare` skips CLAUDE.md / hooks / plugins — used for connectivity preflight
    so a short round-trip is not crushed by this repo's full system prompt.
    """
    binary = resolve_binary()
    if binary is None:
        return RunResult(
            ok=False,
            output="",
            error=(
                f"Claude Code CLI not found as {os.environ.get('CLAUDE_BIN', 'claude')!r}. "
                "Set CLAUDE_BIN to its full path."
            ),
            returncode=127,
            permanent=True,
            error_code="cli_missing",
        )

    workdir = Path(cwd) if cwd is not None else REPO_ROOT
    watchdog = HeartbeatWatchdog(on_heartbeat, heartbeat_seconds)
    watchdog.start()
    try:
        return _execute_claude(
            binary=binary,
            prompt=prompt,
            timeout=timeout,
            env=env,
            redact_values=redact_values,
            recording=recording,
            job_type=job_type,
            max_turns=max_turns,
            cancel_check=cancel_check,
            settings=settings,
            bare=bare,
            system_prompt=system_prompt,
            workdir=workdir,
        )
    finally:
        watchdog.stop()


def _execute_claude(
    *,
    binary: str,
    prompt: str,
    timeout: int,
    env: dict[str, str] | None,
    redact_values: list[str] | None,
    recording: Path | None,
    job_type: str | None,
    max_turns: int | None,
    cancel_check: Callable[[], bool] | None,
    settings: dict[str, Any] | None,
    bare: bool,
    system_prompt: str | None,
    workdir: Path,
) -> RunResult:
    scope: list[str] = []
    if bare:
        scope.append("--bare")
    if system_prompt:
        scope += ["--system-prompt", system_prompt]
    if job_type:
        from cbc.core import toolsets

        scope += toolsets.flags_for(job_type)
    if max_turns:
        scope += ["--max-turns", str(max_turns)]
    settings_flags = _settings_argv(settings)

    # `--` first: the prompt carries project names, file names and text lifted
    # out of a customer's PDF. One starting with `-` was parsed as a flag, and a
    # `--mcp-config` or `--allowed-tools` arriving that way would re-scope the run
    # straight past toolsets.flags_for - which is the whole tool restriction.
    command = [
        binary,
        "--print",
        *settings_flags,
        *scope,
        "--dangerously-skip-permissions",
        "--",
        prompt,
    ]

    # A recorded run narrates itself.
    #
    # `--print` alone emits only the final answer - on a pty, a whole extraction
    # produced 14 bytes - so there is nothing to watch during the minutes that
    # matter. `--output-format stream-json --verbose` makes the CLI report each
    # tool call as it makes it, which is the actual process output and the only
    # form of it that shows progress. (The interactive TUI would be richer still,
    # but it stops on the login-method screen and cannot be driven unattended.)
    if recording is not None:
        from cbc.core import streaming

        streamed = [
            binary,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            *settings_flags,
            *scope,
            "--dangerously-skip-permissions",
            prompt,
        ]
        try:
            returncode, raw = streaming.run_on_pty(
                streamed,
                cwd=workdir,
                env=env,
                timeout=timeout,
                recording=recording,
                redact_values=redact_values,
                cancel_check=cancel_check,
            )
        except (ImportError, OSError) as exc:
            # No pty on this host; fall through to pipes rather than fail the job.
            returncode, raw = None, f"[terminal recording unavailable: {exc}]"
        if returncode is not None:
            text, failure = streaming.summarise(raw)
            if cancel_check and cancel_check():
                return RunResult(
                    ok=False,
                    output=secrets.redact(text[-MAX_LOG_CHARS:], redact_values),
                    error="cancelled by estimator",
                    returncode=130,
                )
            return _interpret(text, failure, returncode, timeout, redact_values)

    try:
        completed = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        return RunResult(
            ok=False,
            output="",
            error=f"could not execute {binary!r}",
            returncode=127,
            permanent=True,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            ok=False, output="", error=f"timed out after {timeout}s", returncode=124
        )

    return _interpret(
        completed.stdout or "", completed.stderr or "", completed.returncode,
        timeout, redact_values,
    )


# Bedrock reports these as 400/403 bodies, not as "failed to authenticate".
# Retrying the same model ID or key will not change the answer.
_BEDROCK_FAILURES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        (
            "on-demand throughput isn't supported",
            "retry with an inference profile",
        ),
        (
            "Bedrock rejected a foundation-model ID. Use a full inference-profile ID "
            "(for example global.anthropic.claude-sonnet-4-5-20250929-v1:0 in ap-south-1), "
            "not a bare anthropic.claude-… ID."
        ),
        "bedrock_model_id",
    ),
    (
        (
            "authorization header is missing",
            "not authorized to perform: bedrock",
            "accessdeniedexception",
        ),
        (
            "Bedrock refused the request. Check the API key (AWS_BEARER_TOKEN_BEDROCK) "
            "or the Fargate task role, and that the model is enabled in this region."
        ),
        "bedrock_auth",
    ),
    (
        ("validationexception", "model identifier is invalid"),
        (
            "Bedrock did not recognise that model ID. Use a region-correct inference "
            "profile (us./eu./apac./global. prefix), not a foundation-model ID."
        ),
        "bedrock_model_id",
    ),
)


def _bedrock_failure(lowered: str) -> tuple[str, str] | None:
    for markers, message, code in _BEDROCK_FAILURES:
        if any(marker in lowered for marker in markers):
            return message, code
    return None


def _interpret(
    stdout: str,
    stderr: str,
    returncode: int,
    timeout: int,
    redact_values: list[str] | None,
) -> RunResult:
    """Turn a finished run into a verdict.

    Shared by the pty path and the pipe path, so "did this succeed?" has one
    answer however the process was spawned.
    """
    # Redact before anything else touches these: the caller stores the output on
    # the job document and the UI renders it.
    output = secrets.redact(stdout[-MAX_LOG_CHARS:], redact_values)
    errors = secrets.redact(stderr[-MAX_LOG_CHARS:], redact_values)

    if returncode == 124:
        return RunResult(
            ok=False,
            output=output,
            error=f"timed out after {timeout}s",
            returncode=124,
            error_code="timeout",
        )
    if returncode == 130:
        return RunResult(
            ok=False,
            output=output,
            error="cancelled by estimator",
            returncode=130,
            error_code="cancelled",
        )

    # The CLI exits 0 on an auth failure, so the exit code alone is not enough.
    lowered = f"{output}\n{errors}".lower()
    bedrock = _bedrock_failure(lowered)
    if bedrock:
        message, code = bedrock
        return RunResult(
            ok=False,
            output=output,
            error=message,
            returncode=returncode,
            permanent=True,
            error_code=code,
        )
    for marker in ("failed to authenticate", "oauth session expired", "invalid api key"):
        if marker in lowered:
            return RunResult(
                ok=False,
                output=output,
                error=(
                    "Claude Code could not authenticate. Configure a provider on "
                    "the settings screen, or sign in with the CLI, then re-run."
                ),
                returncode=returncode,
                permanent=True,
                error_code="auth_failed",
            )

    if returncode != 0:
        detail = errors.strip() or output.strip() or f"claude exited {returncode}"
        if (
            "prompt is too long" in lowered
            or "context window" in lowered
            or "maximum context length" in lowered
        ):
            detail = (
                "Model context window exceeded (Claude Code system prompt/tools "
                "plus completion budget). Use a larger-context provider such as "
                "Anthropic Sonnet for estimating runs. "
                f"{detail}"
            )[:2000]
            return RunResult(
                ok=False,
                output=output,
                error=detail,
                returncode=returncode,
                error_code="context_window",
            )
        return RunResult(
            ok=False,
            output=output,
            error=detail[:2000],
            returncode=returncode,
            error_code="cli_exit",
        )

    return RunResult(ok=True, output=output, error=None, returncode=0)


def preflight(
    env: dict[str, str] | None = None,
    redact_values: list[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> str | None:
    """Return a human-readable problem, or None when the CLI looks usable.

    This is also what the settings screen's Test connection button runs, so a
    misconfigured provider is reported the same way there as it is at startup -
    including the auth-marker scan, which exists because the CLI exits 0 on an
    authentication failure.

    Uses the empty-MCP `preflight` toolset so connectivity checks do not load
    every server schema just to answer one line.
    """
    result = run_claude(
        "Reply with exactly: WORKER_PREFLIGHT_OK",
        timeout=90,
        env=env,
        redact_values=redact_values,
        settings=settings,
        job_type="preflight",
        max_turns=2,
        bare=True,
        system_prompt=(
            "You are a connectivity check. Reply to the user message with the "
            "exact text they request and nothing else."
        ),
    )
    if not result.ok:
        return result.error
    if "WORKER_PREFLIGHT_OK" not in result.output:
        return f"unexpected reply from the CLI: {result.output[:200]!r}"
    return None
