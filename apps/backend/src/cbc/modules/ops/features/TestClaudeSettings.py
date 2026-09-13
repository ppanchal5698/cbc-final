"""POST /api/settings/claude/test - a real one-line pass against the candidate settings."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from cbc.core import secrets
from cbc.modules.ops.domain.claude_settings import ClaudeSettings, is_masked
from cbc.modules.ops.infrastructure.claude_config import load_config
from cbc.modules.ops.api import provider
from cbc.shared.auth import require_admin

# Every settings route is admin-only: they read or write provider credentials,
# spawn CLI processes, or change how every bid behaves.
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


def _validate_provider_urls(body: ClaudeSettings) -> None:
    """Reject a typed base URL that we would send a credential to."""
    try:
        provider.check_base_url(body.baseUrl)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
            if value is None or (is_secret and is_masked(value)):
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
