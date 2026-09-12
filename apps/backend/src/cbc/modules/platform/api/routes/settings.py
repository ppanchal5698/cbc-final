"""Configuring which Claude Code this installation talks to.

Until now the worker inherited whatever environment its shell had, which made
authentication invisible from inside the app and unfixable from outside it. This
router makes the provider a stored, testable choice.

Two ways to authenticate, as asked for:

  1. Sign in through the browser (local development). `claude setup-token` runs
     on a pseudo-terminal, prints an authorization URL, and returns a one-year
     token once the code from the browser is pasted back.
  2. Credentials entered directly - an Anthropic key, a Bedrock region, or a
     gateway base URL plus bearer token. This is the production path.

Secrets are encrypted at rest, returned masked, and never written to the audit
trail - `audit.record` here stores which fields changed, never their values.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from cbc.db import db
from cbc.http.deps import Actor, require_admin
from cbc.domain import freshness as freshness_core
from cbc.services import audit, freshness as freshness_settings, provider
from cbc.core import secrets

# Every route here reads or writes provider credentials, or spawns a CLI process.
# The proxy's only check was "is anyone signed in", so any estimator could read
# which credentials were configured, repoint the gateway, or start processes.
router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_admin)],
)

DOC_ID = "claude"

# The CLI writes to a terminal, so the URL arrives wrapped in an OSC-8 hyperlink
# escape and terminated by BEL rather than by whitespace. Matching on \S+ swallows
# the escape; matching on the host alone misses it, because the authorization
# host is claude.com and not the claude.ai you would expect.
URL_PATTERN = re.compile("https://[^\\s\\x07\\x1b]+oauth/authorize[^\\s\\x07\\x1b]*")

# In-flight `claude setup-token` processes, keyed by the id handed to the
# browser. Process handles stay in-process; session metadata lives in Mongo so
# multi-worker deployments can detect stale or foreign-host sessions.
_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_TTL = 600
API_INSTANCE_ID = f"{socket.gethostname()}-{os.getpid()}"


class ClaudeSettings(BaseModel):
    """Only the fields for the selected mode are read; the rest are ignored."""

    mode: str = Field(default=provider.SUBSCRIPTION)
    oauthToken: str | None = None
    apiKey: str | None = None
    authToken: str | None = None
    bedrockApiKey: str | None = None
    baseUrl: str | None = None
    awsRegion: str | None = None
    model: str | None = None
    smallFastModel: str | None = None


class OAuthCode(BaseModel):
    session: str
    code: str


def _is_masked(value: str) -> bool:
    """Is this the mask the settings screen was shown, rather than a new secret?

    The screen renders a credential as `sk-a********egAA`, and the form posts back
    whatever is in the box. Testing only for a string of asterisks never fired,
    because the mask keeps the first and last four characters - so Save wrote the
    mask over the real credential and Test authenticated with it. A real secret
    never contains a run of asterisks.
    """
    return "****" in value


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_config() -> dict[str, Any]:
    stored = await db.settings.find_one({"_id": DOC_ID}) or provider.default_config()
    # Cloudflare provider was removed; drop any leftover mode so the UI and
    # worker do not try to resolve CLOUDFLARE_* credentials.
    if stored.get("mode") == "cloudflare":
        cleaned = {
            **provider.default_config(),
            "updatedAt": stored.get("updatedAt"),
            "updatedBy": stored.get("updatedBy"),
        }
        await db.settings.replace_one({"_id": DOC_ID}, {"_id": DOC_ID, **cleaned}, upsert=True)
        return cleaned
    return stored


def _is_local_dev() -> bool:
    return os.environ.get("APP_ENV", "development").lower() not in ("production", "prod")


def _sweep() -> None:
    for key, entry in list(_PENDING.items()):
        if time.time() - entry["startedAt"] > _PENDING_TTL:
            _close(key)


async def sweep_oauth_sessions() -> None:
    """Kill abandoned OAuth subprocesses and drop expired Mongo session rows."""
    _sweep()
    now = _now()
    expired = await db.oauth_sessions.find({"expiresAt": {"$lte": now}}).to_list(100)
    for row in expired:
        _close(row["_id"])
        await db.oauth_sessions.delete_one({"_id": row["_id"]})


def _close(key: str) -> None:
    entry = _PENDING.pop(key, None)
    if not entry:
        return
    try:
        entry["process"].kill()
    except Exception:
        pass
    try:
        os.close(entry["fd"])
    except Exception:
        pass


class PipelineSettings(BaseModel):
    """How a new bid behaves when a drawing lands on it."""

    autopilotDefault: bool = False


class FreshnessSettings(BaseModel):
    """How long a price book or last-PO cost stays inside the review window."""

    catalogStaleMonths: int = Field(ge=1, le=freshness_core.MAX_MONTHS)
    discardAfterMonths: int = Field(ge=1, le=freshness_core.MAX_MONTHS)

    @model_validator(mode="after")
    def discard_after_the_review_window(self) -> FreshnessSettings:
        if self.catalogStaleMonths >= self.discardAfterMonths:
            raise ValueError(
                "discardAfterMonths must be greater than catalogStaleMonths"
            )
        return self


@router.get("/pipeline")
async def get_pipeline_settings() -> dict[str, Any]:
    stored = await db.settings.find_one({"_id": "pipeline"}) or {}
    return {
        "autopilotDefault": bool(stored.get("autopilotDefault", False)),
        "note": (
            "Autopilot runs Phase 0-6 in one pass when a drawing is uploaded. The "
            "openings are priced before anyone checks them and everything uncertain "
            "is flagged for review at the end. Nothing is ever sent (NFR-1). Each "
            "bid can override this."
        ),
        "updatedAt": stored.get("updatedAt"),
        "updatedBy": stored.get("updatedBy"),
    }


@router.put("/pipeline")
async def save_pipeline_settings(body: PipelineSettings, actor: Actor) -> dict[str, Any]:
    await db.settings.update_one(
        {"_id": "pipeline"},
        {"$set": {"autopilotDefault": body.autopilotDefault,
                  "updatedAt": _now(), "updatedBy": actor}},
        upsert=True,
    )
    await audit.record(
        "settings.pipeline.update", actor, {},
        after={"autopilotDefault": body.autopilotDefault},
    )
    return await get_pipeline_settings()


@router.get("/freshness")
async def get_freshness_settings() -> dict[str, Any]:
    freshness_settings.clear_cache()
    return freshness_settings.as_payload(await freshness_settings.load())


@router.put("/freshness")
async def save_freshness_settings(body: FreshnessSettings, actor: Actor) -> dict[str, Any]:
    document = {
        "catalogStaleMonths": body.catalogStaleMonths,
        "discardAfterMonths": body.discardAfterMonths,
        "catalogStaleDays": freshness_core.days_from_months(body.catalogStaleMonths),
        "discardAfterDays": freshness_core.days_from_months(body.discardAfterMonths),
        "updatedAt": _now(),
        "updatedBy": actor,
    }
    await db.settings.update_one(
        {"_id": freshness_settings.DOC_ID},
        {"$set": document},
        upsert=True,
    )
    freshness_settings.clear_cache()
    await audit.record(
        "settings.freshness.update",
        actor,
        {},
        after={
            "catalogStaleMonths": body.catalogStaleMonths,
            "discardAfterMonths": body.discardAfterMonths,
        },
    )
    return await get_freshness_settings()


def _validate_provider_urls(body: ClaudeSettings) -> None:
    """Reject a typed base URL that we would send a credential to."""
    try:
        provider.check_base_url(body.baseUrl)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/claude")
async def get_claude_settings() -> dict[str, Any]:
    config = await load_config()
    return {
        **provider.public_config(config),
        "localDev": _is_local_dev(),
        "cliAvailable": shutil.which("claude") is not None,
    }


@router.put("/claude")
async def save_claude_settings(
    body: ClaudeSettings, actor: Actor
) -> dict[str, Any]:
    if body.mode not in provider.MODES:
        raise HTTPException(400, f"unknown mode {body.mode!r}")

    current = await load_config()
    incoming = body.model_dump(exclude_none=True)
    document: dict[str, Any] = {"mode": body.mode}
    changed: list[str] = []

    for field, (_, is_secret) in provider.FIELDS[body.mode].items():
        value = incoming.get(field)
        if value is None or (is_secret and _is_masked(value)):
            # The screen sent its own mask back, which means "leave this alone".
            document[field] = current.get(field)
            continue
        document[field] = secrets.encrypt(value) if is_secret else value
        if document[field] != current.get(field):
            changed.append(field)

    _validate_provider_urls(body)

    if body.mode != current.get("mode"):
        changed.append("mode")

    document["updatedAt"] = _now()
    document["updatedBy"] = actor
    await db.settings.update_one({"_id": DOC_ID}, {"$set": document}, upsert=True)
    await asyncio.to_thread(provider.persist_env_file, document)

    # Field names only. The values are exactly what must never reach the trail.
    await audit.record(
        "settings.claude.update",
        actor,
        {},
        after={"mode": body.mode, "changed": sorted(set(changed))},
        note="credential values are not recorded",
    )

    saved = await load_config()
    return {**provider.public_config(saved), "changed": sorted(set(changed))}


@router.post("/claude/test")
async def test_claude_settings(body: ClaudeSettings | None = None) -> dict[str, Any]:
    """Run a real one-line pass against the candidate settings.

    Tests what was typed rather than what was saved, so a wrong key is caught
    before it becomes the configuration every job uses.
    """
    from cbc.core import claude_cli as runner

    if body is not None:
        _validate_provider_urls(body)

    if body is not None and body.mode in provider.MODES:
        stored = await load_config()
        candidate: dict[str, Any] = {"mode": body.mode}
        incoming = body.model_dump(exclude_none=True)
        for field, (_, is_secret) in provider.FIELDS[body.mode].items():
            value = incoming.get(field)
            if value is None or (is_secret and _is_masked(value)):
                candidate[field] = stored.get(field)
            else:
                candidate[field] = secrets.encrypt(value) if is_secret else value
    else:
        candidate = await load_config()

    env, _ = provider.build_env(candidate)
    problem = await asyncio.to_thread(
        runner.preflight,
        env,
        provider.secret_values(candidate),
        provider.claude_settings_overlay(candidate),
    )

    return {
        "ok": problem is None,
        "provider": provider.describe(candidate),
        "error": problem,
    }


@router.get("/ollama/models")
async def list_ollama_models(
    baseUrl: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return models from a host Ollama instance for the settings model picker."""
    import httpx

    resolved = baseUrl or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        provider.check_base_url(resolved)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    url = resolved.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            502,
            f"Could not reach Ollama at {resolved!r}: {exc}",
        ) from exc

    models = []
    for entry in payload.get("models") or []:
        models.append(
            {
                "name": entry.get("name"),
                "size": entry.get("size"),
                "modifiedAt": entry.get("modified_at"),
            }
        )
    return {"baseUrl": resolved, "models": models}


@router.post("/claude/oauth/start")
async def oauth_start() -> dict[str, Any]:
    """Begin `claude setup-token` and return the URL to open in a browser.

    The CLI drives this through a terminal prompt, so it needs a pty. There is no
    pty on Windows - the flow is reported as unavailable there rather than
    half-working, and the token can still be generated by hand and pasted in.
    """
    if not _is_local_dev():
        raise HTTPException(
            403,
            "Browser sign-in is a local development path. In production, configure "
            "a provider credential or an IAM role.",
        )

    try:
        import pty
    except ImportError:
        raise HTTPException(
            501,
            "This host has no pty, so the interactive flow cannot run. Run "
            "`claude setup-token` yourself and paste the token in as the "
            "subscription credential.",
        )

    binary = shutil.which("claude")
    if binary is None:
        raise HTTPException(503, "the Claude Code CLI is not installed on this host")

    _sweep()
    import subprocess

    controller, follower = pty.openpty()

    # A pty defaults to 80 columns and the CLI hard-wraps to it, which puts a
    # CRLF into the middle of both the authorization URL and anything else long.
    # The URL survived only because the terminal hyperlink escape carries an
    # unwrapped copy - not something to rely on. Give it a wide window instead.
    try:
        import fcntl
        import struct
        import termios

        fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 400, 0, 0))
    except (ImportError, OSError):
        pass  # cosmetic; extraction still has the hyperlink copy to fall back on

    process = subprocess.Popen(
        [binary, "setup-token"],
        stdin=follower,
        stdout=follower,
        stderr=follower,
        close_fds=True,
    )
    os.close(follower)

    buffered = await asyncio.to_thread(_read_until, controller, URL_PATTERN, 60)
    match = URL_PATTERN.search(buffered)
    if not match:
        try:
            process.kill()
        finally:
            os.close(controller)
        raise HTTPException(
            504,
            "The CLI did not print an authorization URL. Output was: "
            + secrets.redact(_clean(buffered)[-500:]),
        )

    session = uuid.uuid4().hex
    expires = _now() + timedelta(seconds=_PENDING_TTL)
    await db.oauth_sessions.insert_one(
        {
            "_id": session,
            "hostId": API_INSTANCE_ID,
            "url": match.group(0),
            "startedAt": _now(),
            "expiresAt": expires,
        }
    )
    _PENDING[session] = {
        "process": process,
        "fd": controller,
        "startedAt": time.time(),
        "buffer": buffered,
    }
    return {"session": session, "url": match.group(0), "expiresIn": _PENDING_TTL}


@router.post("/claude/oauth/code")
async def oauth_code(body: OAuthCode, actor: Actor) -> dict[str, Any]:
    """Hand the browser's authorization code back to the CLI and store the token."""
    stored = await db.oauth_sessions.find_one({"_id": body.session})
    if not stored:
        raise HTTPException(404, "that sign-in has expired - start it again")
    if stored.get("hostId") != API_INSTANCE_ID:
        raise HTTPException(
            409,
            "this sign-in was started on another API instance; complete it there "
            "or start a new sign-in on this one",
        )

    entry = _PENDING.get(body.session)
    if not entry:
        await db.oauth_sessions.delete_one({"_id": body.session})
        raise HTTPException(404, "that sign-in has expired - start it again")

    code = body.code.strip()
    if not code:
        raise HTTPException(400, "no code supplied")

    # Carriage return, not newline. The prompt is an Ink TUI reading raw
    # keypresses, where Enter arrives as \r - a \n is accepted into the field and
    # never submitted, so the code sits there echoing asterisks until the read
    # times out. The code and the Enter go as separate writes because that is
    # what a paste followed by a keypress actually looks like.
    os.write(entry["fd"], code.encode("utf-8"))
    await asyncio.sleep(0.2)
    os.write(entry["fd"], b"\r")

    output = await asyncio.to_thread(_read_until, entry["fd"], _DONE_PATTERN, 120)

    # Read the token out of the cleaned text, not the raw stream. The CLI prints
    # it inside a styled panel, so colour escapes land between the characters and
    # a raw search misses a token that was created perfectly well - and the CLI
    # shows it exactly once, so losing it here means signing in all over again.
    readable = _clean(output)

    # Every rendering of the token, longest first, then verified for real.
    #
    # The CLI redraws its frame as it works, so the buffer holds the token several
    # times over, and an intermediate frame can carry a style escape spliced into
    # the middle of it. Stripping that escape takes a character of the token with
    # it - which is how a token that had been minted perfectly well was stored one
    # character short and rejected as an invalid bearer token, with nothing in the
    # UI to suggest anything but a bad credential. The complete rendering is the
    # longest one, and the only way to be sure is to make Claude Code use it.
    candidates = sorted(set(_TOKEN_PATTERN.findall(readable)), key=len, reverse=True)
    match = await _first_working_token(candidates)
    if not match:
        failure = _OAUTH_ERROR.search(readable)
        if candidates and not failure:
            _close(body.session)
            raise HTTPException(
                502,
                {
                    "message": "The CLI issued a token but Claude Code would not "
                    "accept it. It has to be generated again - the CLI shows it only "
                    "once.",
                    "hint": "Start the sign-in again.",
                },
            )

        # A rejected code leaves the CLI on "Press Enter to retry", where it
        # swallows the next code as the keypress it is waiting for. Acknowledge it
        # here so the session is left back at the prompt, and a second attempt
        # works instead of hanging until the read times out.
        if not failure:
            _close(body.session)
            raise HTTPException(
                502,
                {
                    "message": "No token came back from the CLI. It reported: "
                    + secrets.redact(readable[-400:])
                },
            )

        os.write(entry["fd"], b"\r")
        retry_output = await asyncio.to_thread(_read_until, entry["fd"], _PROMPT_PATTERN, 30)

        # Retrying does not re-offer the same authorization - the CLI starts a new
        # one, with a new state and code challenge. Handing back the old URL would
        # send the estimator round a loop where every code is rejected for being
        # built against a challenge the CLI has already discarded.
        retry_url = URL_PATTERN.search(retry_output)
        raise HTTPException(
            502,
            {
                "message": failure.group(0),
                "url": retry_url.group(0) if retry_url else None,
                "hint": (
                    "That code was rejected. Use the new link - the previous one is "
                    "no longer valid."
                    if retry_url
                    else "Start the sign-in again."
                ),
            },
        )

    _close(body.session)
    await db.oauth_sessions.delete_one({"_id": body.session})

    token = match
    await db.settings.update_one(
        {"_id": DOC_ID},
        {
            "$set": {
                "mode": provider.SUBSCRIPTION,
                "oauthToken": secrets.encrypt(token),
                "updatedAt": _now(),
                "updatedBy": actor,
            }
        },
        upsert=True,
    )
    await audit.record(
        "settings.claude.oauth",
        actor,
        {},
        after={"mode": provider.SUBSCRIPTION},
        note="subscription token stored; value not recorded",
    )

    saved = await load_config()
    return {**provider.public_config(saved), "signedIn": True}


# `claude setup-token` prints an sk-ant-oat… token on success.
_TOKEN_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")

# What ends the wait, either way. Without the failure half, a rejected code
# would block for the full timeout before reporting anything.
_OAUTH_ERROR = re.compile("OAuth error:[^\\r\\n]*|Request failed with status code [0-9]+")
_DONE_PATTERN = re.compile(_TOKEN_PATTERN.pattern + "|" + _OAUTH_ERROR.pattern)

# The prompt as it reads once the escapes are stripped - the CLI writes it
# with cursor moves between the words, so the spaces do not survive.
_PROMPT_PATTERN = re.compile("[Pp]aste ?code ?here")

# Cursor moves, colours and hyperlink wrappers, so an error can be read by a human.
_ANSI = re.compile("\\x1b\\[[0-9;?]*[A-Za-z]|\\x1b][^\\x07\\x1b]*(?:\\x07|\\x1b\\\\)|\\x1b\\([AB]|[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]")


def _clean(text: str) -> str:
    return _ANSI.sub("", text)


def _read_until(fd: int, pattern: re.Pattern[str], timeout: int) -> str:
    """Drain a pty until the pattern shows up, the process ends, or time runs out."""
    import select

    deadline = time.time() + timeout
    buffered = ""
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 1.0)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:  # the child exited and closed its end
            break
        if not chunk:
            break
        buffered += chunk.decode("utf-8", errors="replace")
        # Against both the raw stream and the stripped one. The CLI positions the
        # cursor between words, so "Paste code here" arrives as
        # "Paste\x1b[8Gcode\x1b[13Ghere" and only matches once the escapes are
        # gone - a raw-only test silently waits out the whole timeout instead.
        if pattern.search(buffered) or pattern.search(_clean(buffered)):
            break
    return buffered


async def _first_working_token(candidates: list[str]) -> str | None:
    """Return the first candidate Claude Code actually accepts, or None.

    Verifying costs one short CLI round trip, which is worth it: the CLI shows the
    token exactly once, so storing a broken one silently is unrecoverable - the
    estimator sees a configured credential that fails on every job.
    """
    from cbc.core import claude_cli as runner

    for candidate in candidates:
        env, _ = provider.build_env({"mode": provider.SUBSCRIPTION, "oauthToken": candidate})
        if await asyncio.to_thread(runner.preflight, env, [candidate]) is None:
            return candidate
    return None
