"""GET and PUT /api/settings/parsing - LlamaParse runtime parser settings.

There is no container to configure any more: parsing is a cloud call, so the
whole surface is the API key, the tier and the windowing knobs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

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

    apiKey: str | None = None
    tier: str | None = None
    lang: str | None = None
    windowPages: int | None = Field(default=None, ge=1, le=200)
    windowTimeoutSeconds: int | None = Field(default=None, ge=60, le=7200)
    waitMaxSeconds: int | None = Field(default=None, ge=60, le=7200)


async def load_config() -> dict[str, Any]:
    return await settings_collection().find_one({"_id": parsing_config.DOC_ID}) or {}


@router.get("/parsing")
async def get_parsing_settings() -> dict[str, Any]:
    # No upstream health probe: against a cloud API the first parse request is
    # the health check, and a synchronous third-party call on every settings page
    # load is a bad trade. `POST /parsing/test` is the deliberate version.
    stored = await load_config()
    payload = parsing_config.public_config(stored)
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
