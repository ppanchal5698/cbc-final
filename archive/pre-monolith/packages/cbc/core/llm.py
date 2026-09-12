"""Single reusable LLM client.

Resolves credentials the same way the worker does (provider.build_env), so the
model and gateway can be swapped without touching pipeline logic.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("cbc.llm")

# Sonnet 5 is the current model in the tier this pipeline was written for; the
# pin it replaced (a dated Sonnet 4 snapshot) named a model two generations back.
# Overridable per deployment with ANTHROPIC_MODEL - moving to another tier is a
# cost and capability decision, so it is not made here.
DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"LLM response contained no JSON object: {text[:200]}")
    return json.loads(match.group(0))


@dataclass
class LLMResponse:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    document_id: str | None = None
    section_id: str | None = None


@dataclass
class LLMClient:
    """Anthropic Messages API client using env from provider.build_env."""

    api_key: str | None = None
    auth_token: str | None = None
    base_url: str = "https://api.anthropic.com"
    model: str = DEFAULT_MODEL
    use_bedrock: bool = False
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LLMClient:
        env = env or dict(os.environ)
        return cls(
            api_key=env.get("ANTHROPIC_API_KEY") or None,
            auth_token=env.get("ANTHROPIC_AUTH_TOKEN") or env.get("CLAUDE_CODE_OAUTH_TOKEN"),
            base_url=(env.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/"),
            model=env.get("ANTHROPIC_MODEL") or DEFAULT_MODEL,
            use_bedrock=env.get("CLAUDE_CODE_USE_BEDROCK") == "1",
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        elif self.auth_token:
            headers["authorization"] = f"Bearer {self.auth_token}"
        return headers

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        document_id: str | None = None,
        section_id: str | None = None,
        prompt_version: str | None = None,
    ) -> LLMResponse:
        if not self.api_key and not self.auth_token:
            raise RuntimeError(
                "no LLM credentials configured — set ANTHROPIC_API_KEY or configure a provider"
            )

        url = f"{self.base_url}/v1/messages"
        body = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        input_estimate = estimate_tokens(system + user)
        started = time.monotonic()

        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, headers=self._headers(), json=body)
            response.raise_for_status()
            payload = response.json()

        latency_ms = int((time.monotonic() - started) * 1000)
        blocks = payload.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or input_estimate)
        output_tokens = int(usage.get("output_tokens") or estimate_tokens(text))

        audit = {
            "document_id": document_id,
            "section_id": section_id,
            "prompt_version": prompt_version,
            "model": payload.get("model") or self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        }
        self.audit_log.append(audit)
        log.info("llm call %s", audit)

        return LLMResponse(
            data=_extract_json(text),
            model=audit["model"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            document_id=document_id,
            section_id=section_id,
        )
