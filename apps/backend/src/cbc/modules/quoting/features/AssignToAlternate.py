"""POST /api/projects/{code}/alternates/assign - move openings or quote lines into a group.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_assign_payload(
    raw: bytes,
    *,
    query_ids: list[str] | None,
    query_alternate: str | None,
    query_scope: str,
) -> tuple[list[str], str | None, str]:
    """Accept legacy array bodies, object bodies, and query-param fallbacks.

    FastAPI cannot expose ``AlternateAssign`` alongside top-level ``alternate`` /
    ``scope`` / ``ids`` parameters — the names collide and the frontend object
    body silently assigns to the base bid. Parse manually instead.
    """
    line_ids: list[str] | None = None
    alternate = query_alternate
    scope = query_scope

    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "invalid JSON body") from exc

        if isinstance(payload, list):
            if not all(isinstance(item, str) for item in payload):
                raise HTTPException(400, "ids must be a list of line id strings")
            line_ids = payload
        elif isinstance(payload, dict):
            raw_ids = payload.get("ids")
            if raw_ids is None:
                raise HTTPException(400, "provide ids in the JSON body or as query parameters")
            if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
                raise HTTPException(400, "ids must be a list of line id strings")
            line_ids = raw_ids
            if "alternate" in payload:
                alt = payload["alternate"]
                if alt is not None and not isinstance(alt, str):
                    raise HTTPException(400, "alternate must be a string or null")
                alternate = alt
            if "scope" in payload:
                scope = payload["scope"]
        else:
            raise HTTPException(400, "body must be a list of ids or an object with an ids field")

    if not line_ids:
        line_ids = query_ids
    if not line_ids:
        raise HTTPException(400, "provide ids in the JSON body or as query parameters")

    if scope not in ("line-items", "quote-lines"):
        raise HTTPException(400, "scope must be 'line-items' or 'quote-lines'")

    return line_ids, alternate, scope


@router.post("/alternates/assign")
async def assign_to_alternate(
    code: str,
    actor: Actor,
    request: Request,
    ids: list[str] | None = Query(default=None),
    alternate: str | None = Query(default=None),
    scope: str = Query(default="line-items"),
) -> dict:
    line_ids, alternate, scope = _parse_assign_payload(
        await request.body(),
        query_ids=ids,
        query_alternate=alternate,
        query_scope=scope,
    )

    project = await load(code)
    object_ids = [oid(i) for i in line_ids]

    now = _now()
    if scope == "line-items":
        moved = await extraction_openings.assign_group(project["_id"], object_ids, alternate, at=now)
    else:
        result = await estimate_lines().update_many(
            {
                "_id": {"$in": object_ids},
                "projectId": project["_id"],
                "alternateGroup": {"$ne": alternate},
            },
            {"$set": {"alternateGroup": alternate, "updatedAt": now}},
        )
        moved = result.modified_count

    await audit.record(
        "alternate.assign",
        actor,
        {"projectId": project["_id"]},
        after={"alternate": alternate, "moved": moved, "scope": scope},
    )
    return {"moved": moved, "alternate": alternate}
