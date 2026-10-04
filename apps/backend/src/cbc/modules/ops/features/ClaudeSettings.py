"""GET and PUT /api/settings/claude - which Claude Code this installation talks to.

The worker used to inherit whatever environment its shell had, which made
authentication invisible from inside the app and unfixable from outside it. This
makes the provider a stored, testable choice. Credentials entered here - an
Anthropic key, a Bedrock region, a gateway base URL plus bearer token - are the
production path; browser sign-in is ClaudeOAuth.

Secrets are encrypted at rest, returned masked, and never written to the audit
trail - `audit.record` here stores which fields changed, never their values.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from cbc.modules.ops.infrastructure import secrets
from cbc.modules.ops.api import audit
from cbc.modules.ops.domain.claude_settings import ClaudeSettings, is_masked
from cbc.modules.ops.infrastructure.claude_config import DOC_ID, load_config
from cbc.modules.ops.infrastructure.collections import settings_collection
from cbc.modules.ops.api import provider
from cbc.shared.auth import Actor, require_admin

# Every settings route is admin-only: they read or write provider credentials,
# spawn CLI processes, or change how every bid behaves.
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_local_dev() -> bool:
    return os.environ.get("APP_ENV", "development").lower() not in ("production", "prod")


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

    # Several modes name a field the same thing - `model`, `smallFastModel` and
    # `baseUrl` all appear in more than one - so "keep what is stored" is only
    # meaningful while the mode is unchanged. Across a switch the stored value
    # belongs to a different provider, and carrying it over put a Bedrock
    # inference-profile id in as an Ollama model name: a switch that looked
    # clean and then failed on the first job.
    same_mode = body.mode == current.get("mode")

    for field, (_, is_secret) in provider.FIELDS[body.mode].items():
        value = incoming.get(field)
        if value is None or (is_secret and is_masked(value)):
            # The screen sent its own mask back, which means "leave this alone".
            document[field] = current.get(field) if same_mode else None
            continue
        document[field] = secrets.encrypt(value) if is_secret else value
        if document[field] != current.get(field):
            changed.append(field)

    # Fields belonging to the mode being left. $set merges, so without this they
    # stay on the document for ever - the doc accumulated awsRegion and
    # bedrockApiKey long after Bedrock had been switched away from.
    stale = {
        field
        for mode in provider.MODES
        for field in provider.FIELDS[mode]
        if field not in provider.FIELDS[body.mode]
    }

    _validate_provider_urls(body)

    if (needed := provider.missing_requirement(document)) is not None:
        raise HTTPException(
            400,
            f"{body.mode} needs {needed}. Saving it without one reports success "
            "and then fails on the first job.",
        )

    if body.mode != current.get("mode"):
        changed.append("mode")

    document["updatedAt"] = _now()
    document["updatedBy"] = actor
    update: dict[str, Any] = {"$set": document}
    if stale:
        update["$unset"] = {field: "" for field in sorted(stale)}
    await settings_collection().update_one({"_id": DOC_ID}, update, upsert=True)
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
