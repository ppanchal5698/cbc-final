"""Ask the model one narrow, typed question and get a validated answer or None.

The pipeline used to hand whole phases to agent sessions that wrote documents
and called fifty tools, and one bad field in a document killed the job. Here the
code does the work and asks only what it cannot decide - which of these catalog
rows is the specified part, what does this cropped schedule say - with the
answer's shape fixed by a pydantic model. An answer that will not validate is
retried once with the error, then comes back as None, and the caller flags the
row for an estimator. A question never fails a job.

No question gets tools beyond reading the images it was given, so nothing asked
here can send, write or delete (NFR-1, file safety) whatever it answers.

Two transports, chosen by the provider configured in Settings:
- an Anthropic API key: the Messages API, the answer forced through a tool whose
  input schema is the answer model's;
- everything else (subscription, Bedrock, Ollama, NIM): `claude --print
  --json-schema`, which already speaks each of those providers.

`shared` may not import modules, so the caller resolves the provider
(`cbc.modules.ops.api.ai`) and hands this module a transport.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger("cbc.ai")

T = TypeVar("T", bound=BaseModel)

# (instructions, prompt, images, answer schema) -> the raw answer object.
Transport = Callable[[str, str, Sequence[Path], dict[str, Any]], dict[str, Any]]

DEFAULT_API_MODEL = "claude-sonnet-5-5"


class TransportError(RuntimeError):
    """The provider could not be reached or returned no answer."""


@dataclass(frozen=True)
class Question(Generic[T]):
    """One kind of question: what it is for, and the shape of its answer."""

    name: str
    version: int  # bump when the instructions change, so cached answers expire
    instructions: str
    answer: type[T]


@dataclass(frozen=True)
class Asked(Generic[T]):
    answer: T | None
    error: str | None = None
    cached: bool = False


def cache_key(question: Question[Any], prompt: str, images: Sequence[Path]) -> str:
    digest = hashlib.sha256(f"{question.name}:{question.version}\n{prompt}".encode("utf-8"))
    for image in images:
        digest.update(hashlib.sha256(Path(image).read_bytes()).digest())
    return digest.hexdigest()


def ask(
    question: Question[T],
    prompt: str,
    *,
    transport: Transport,
    images: Sequence[Path] = (),
    cache: MutableMapping[str, dict[str, Any]] | None = None,
) -> Asked[T]:
    """The validated answer, or None with the reason. Never raises for content."""
    key = cache_key(question, prompt, images) if cache is not None else ""
    if cache is not None and key in cache:
        try:
            return Asked(question.answer.model_validate(cache[key]), cached=True)
        except ValidationError:
            pass  # an answer cached under an older model: ask again
    schema = question.answer.model_json_schema()
    text = prompt
    error = None
    for _attempt in range(2):
        try:
            raw = transport(question.instructions, text, images, schema)
        except TransportError as exc:
            log.warning("ai %s: %s", question.name, exc)
            return Asked(None, error=str(exc))
        try:
            answer = question.answer.model_validate(raw)
        except ValidationError as exc:
            error = f"answer did not fit the schema: {exc.errors()[:3]}"
            text = f"{prompt}\n\nYour previous answer was rejected - {error}. Answer again."
            continue
        if cache is not None:
            cache[key] = answer.model_dump(mode="json")
        return Asked(answer)
    return Asked(None, error=error)


# ── transports ───────────────────────────────────────────────────────────────

def api_transport(env: dict[str, str], *, timeout: float = 120.0) -> Transport:
    """Messages API with the answer forced through one tool."""
    api_key = env.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise TransportError("no ANTHROPIC_API_KEY for the API transport")
    base_url = (env.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
    model = env.get("ANTHROPIC_MODEL") or DEFAULT_API_MODEL

    def send(instructions: str, prompt: str, images: Sequence[Path], schema: dict[str, Any]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png",
                           "data": base64.b64encode(Path(image).read_bytes()).decode("ascii")},
            }
            for image in images
        ]
        content.append({"type": "text", "text": prompt})
        body = {
            "model": model,
            "max_tokens": 4096,
            "system": instructions,
            "messages": [{"role": "user", "content": content}],
            "tools": [{"name": "answer", "description": "Give the answer.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "answer"},
        }
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            response = httpx.post(f"{base_url}/v1/messages", headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TransportError(f"Messages API: {exc}") from exc
        for block in response.json().get("content") or []:
            if block.get("type") == "tool_use":
                return block.get("input") or {}
        raise TransportError("Messages API returned no answer")

    return send


def cli_transport(env: dict[str, str], *, claude_bin: str | None = None, timeout: int = 300) -> Transport:
    """`claude --print --json-schema`, in an empty directory, able to read only its images."""
    binary = claude_bin or env.get("CLAUDE_BIN") or "claude"

    def send(instructions: str, prompt: str, images: Sequence[Path], schema: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="cbc-ai-") as workdir:
            names = []
            for index, image in enumerate(images):
                name = f"image_{index + 1}{Path(image).suffix or '.png'}"
                shutil.copyfile(image, Path(workdir) / name)
                names.append(name)
            text = prompt
            if names:
                text = "Read these image files first: " + ", ".join(names) + "\n\n" + prompt
            argv = [
                binary, "--print", "--output-format", "json", "--no-session-persistence",
                "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
                "--max-turns", str(2 + len(names)),
                "--tools", "Read" if names else "",
                "--append-system-prompt", instructions,
                "--json-schema", json.dumps(schema),
                text,
            ]
            try:
                done = subprocess.run(argv, cwd=workdir, env={**os.environ, **env}, capture_output=True,
                                      text=True, timeout=timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TransportError(f"claude CLI: {exc}") from exc
        try:
            result = json.loads(done.stdout)
        except ValueError as exc:
            raise TransportError(f"claude CLI exited {done.returncode}: {done.stderr.strip()[:200]}") from exc
        if result.get("is_error") or not isinstance(result.get("structured_output"), dict):
            raise TransportError(f"claude CLI gave no answer: {str(result.get('result'))[:200]}")
        return result["structured_output"]

    return send


def transport_for(mode: str, env: dict[str, str]) -> Transport:
    """The API for an Anthropic key; the CLI for every other configured provider."""
    if mode == "anthropic_api" and env.get("ANTHROPIC_API_KEY"):
        return api_transport(env)
    return cli_transport(env)
