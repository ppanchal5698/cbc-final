"""GET and PUT /api/settings/parsing - MinerU runtime parser settings.

Container settings (VRAM, base image, concurrent requests) live in
`infra/mineru/<profile>.env` and are shown read-only from MinerU `/health`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import audit, parsing_config
from cbc.modules.ops.infrastructure.collections import settings_collection
from cbc.shared.auth import Actor, require_admin

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)]
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ParsingSettingsBody(BaseModel):
    """Runtime PARSER_* values the Settings screen may save."""

    url: str | None = None
    profile: str | None = None
    backend: str | None = None
    effort: str | None = None
    method: str | None = None
    lang: str | None = None
    tables: bool | None = None
    formulas: bool | None = None
    imageAnalysis: bool | None = None
    windowPages: int | None = Field(default=None, ge=1, le=200)
    windowTimeoutSeconds: int | None = Field(default=None, ge=60, le=7200)
    waitMaxSeconds: int | None = Field(default=None, ge=60, le=7200)


async def load_config() -> dict[str, Any]:
    return await settings_collection().find_one({"_id": parsing_config.DOC_ID}) or {}


async def mineru_health(url: str) -> dict[str, Any]:
    """GET MinerU /health. Returns the JSON body or {"error": ...}."""
    base = url.rstrip("/")
    if not base:
        return {"error": "PARSER_URL is empty — parsing is off"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base}/health")
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/parsing")
async def get_parsing_settings() -> dict[str, Any]:
    stored = await load_config()
    payload = parsing_config.public_config(stored)
    resolved, _ = parsing_config.resolve(stored)
    payload["mineru"] = await mineru_health(str(resolved.get("url") or ""))
    payload["updatedAt"] = stored.get("updatedAt")
    payload["updatedBy"] = stored.get("updatedBy")
    return payload


@router.put("/parsing")
async def save_parsing_settings(
    body: ParsingSettingsBody, actor: Actor
) -> dict[str, Any]:
    current = await load_config()
    incoming = body.model_dump(exclude_none=True)
    document: dict[str, Any] = dict(current)
    changed: list[str] = []

    _, sources = parsing_config.resolve(current)
    for field, value in incoming.items():
        if sources.get(field) == "env":
            # Process env owns this field; ignore the typed value.
            continue
        if document.get(field) != value:
            changed.append(field)
        document[field] = value

    # Validate the merged effective view after applying non-locked fields.
    merged, _ = parsing_config.resolve(document, prefer_config=True)
    problems = parsing_config.validate(merged)
    if problems:
        raise HTTPException(400, "; ".join(problems))

    document["updatedAt"] = _now()
    document["updatedBy"] = actor
    # Drop Mongo metadata keys before upsert shape.
    to_store = {
        key: document[key]
        for key in (
            *parsing_config.FIELDS,
            "updatedAt",
            "updatedBy",
        )
        if key in document
    }
    await settings_collection().update_one(
        {"_id": parsing_config.DOC_ID}, {"$set": to_store}, upsert=True
    )
    await asyncio.to_thread(parsing_config.persist_env_file, to_store)

    await audit.record(
        "settings.parsing.update",
        actor,
        {},
        after={"changed": sorted(set(changed))},
        note="parser values are recorded by field name only",
    )
    return await get_parsing_settings()
