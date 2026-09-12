"""Read and update the repo `.env` without disturbing unrelated keys.

Settings persists provider credentials here so a Bedrock API key typed on the
screen is the same file native runs and Compose interpolation already use.
Process environment still wins (Fargate / Secrets Manager). This file is the
layer between that and Mongo: the worker rereads it on every job, so a Save
takes effect without a restart.

`CBC_ENV_FILE` relocates the path (tests). A missing or unwritable file is not
fatal — Mongo remains the live store.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

from cbc.core.paths import repo_root

log = logging.getLogger("cbc.envfile")

_ASSIGNMENT = re.compile(
    r"^((?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$"
)

_SECTION = "# ── Claude Code (written by Settings → Claude Code) ────────────"


def path() -> Path:
    override = os.environ.get("CBC_ENV_FILE")
    if override:
        return Path(override)
    return repo_root() / ".env"


def read() -> dict[str, str]:
    """Plaintext assignments in the env file. Missing file → empty dict."""
    target = path()
    try:
        if not target.is_file():
            return {}
        text = target.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_assignment(line)
        if parsed is None:
            continue
        _, key, value = parsed
        values[key] = value
    return values


def apply_to_environ(*, skip: set[str] | frozenset[str] | None = None) -> None:
    """Fill gaps in the process environment from `.env`. Never overrides.

    Provider-managed variables are skipped so a key stored in the file does not
    lock the settings screen (that lock is reserved for Fargate / Secrets
    Manager, which inject into the process itself).
    """
    ignored = skip or set()
    for key, value in read().items():
        if key in ignored:
            continue
        os.environ.setdefault(key, value)


def upsert(updates: dict[str, str | None]) -> bool:
    """Write `updates` into `.env`. `None` removes the key.

    Preserves comments and unrelated assignments. Returns False when the file
    cannot be written (no mount, read-only, Docker created a directory).
    """
    if not updates:
        return True
    target = path()
    if target.exists() and not target.is_file():
        log.warning(
            "CBC env file %s is not a regular file (Docker creates a directory "
            "when the host path is missing). Create the file on the host first.",
            target,
        )
        return False

    try:
        original = target.read_text(encoding="utf-8") if target.is_file() else ""
    except OSError as exc:
        log.warning("could not read %s: %s", target, exc)
        return False

    lines = original.splitlines()
    pending = dict(updates)
    rewritten: list[str] = []
    for line in lines:
        parsed = _parse_assignment(line.strip()) if line.strip() and not line.strip().startswith("#") else None
        if parsed is None:
            rewritten.append(line)
            continue
        prefix, key, _ = parsed
        if key not in pending:
            rewritten.append(line)
            continue
        value = pending.pop(key)
        if value is None:
            continue
        rewritten.append(f"{prefix}{key}={_quote(value)}")

    additions = [(key, value) for key, value in pending.items() if value is not None]
    if additions:
        if rewritten and rewritten[-1].strip():
            rewritten.append("")
        if _SECTION not in original:
            rewritten.append(_SECTION)
        for key, value in additions:
            rewritten.append(f"{key}={_quote(value)}")

    text = "\n".join(rewritten)
    if text and not text.endswith("\n"):
        text += "\n"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".env.", dir=str(target.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            try:
                os.replace(tmp_name, target)
            except OSError as replace_exc:
                # Single-file Docker bind mounts (esp. Docker Desktop on Windows)
                # reject replacing the mount point: Errno 16 EBUSY. Write in place.
                if getattr(replace_exc, "errno", None) not in (16, 26):
                    raise
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except OSError as exc:
        log.warning("could not write %s: %s", target, exc)
        return False
    return True


def _parse_assignment(line: str) -> tuple[str, str, str] | None:
    match = _ASSIGNMENT.match(line)
    if not match:
        return None
    prefix, key, raw = match.group(1), match.group(2), match.group(3)
    return prefix, key, _unquote(raw)


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        inner = text[1:-1]
        if text[0] == '"':
            inner = (
                inner.replace("\\\\", "\0")
                .replace("\\n", "\n")
                .replace('\\"', '"')
                .replace("\0", "\\")
            )
        return inner
    if " #" in text:
        text = text.split(" #", 1)[0].rstrip()
    return text


def _quote(value: str) -> str:
    if value == "" or re.search(r"[\s#\"'\\]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
