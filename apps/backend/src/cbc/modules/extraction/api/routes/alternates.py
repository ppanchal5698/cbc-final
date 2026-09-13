"""Alternate line groups on a bid — interim structure only (Matrix 4.1 / FR-14)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from cbc.db import db
from cbc.shared.mongo import oid
from cbc.shared.auth import Actor
from cbc.schemas import AlternateCreate
from cbc.modules.projects.api.lookup import load
from cbc.modules.ops.api import audit
from cbc.services import pricing

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])

PENDING_NOTE = (
    "How an addendum reconciles against the previous version, and whether an "
    "alternate inherits the base bid's confirmations, are still open questions "
    "(Matrix 4.1 / Open Item 11). Differences are flagged, never merged."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/alternates")
async def list_alternates(code: str) -> dict[str, Any]:
    """Every line group on this bid, with its own independent total."""
    project = await load(code)
    project_id = project["_id"]

    names = list(project.get("alternates") or [])
    names += await db.line_items.distinct("alternateGroup", {"projectId": project_id})
    names += await db.quote_lines.distinct("alternateGroup", {"projectId": project_id})
    groups = [None] + sorted({n for n in names if n})

    quote = await db.quotes.find_one({"projectId": project_id}) or {}
    state = quote.get("taxJurisdiction") or project.get("state")

    out = []
    for group in groups:
        query = {"projectId": project_id, "alternateGroup": group}
        lines = await db.quote_lines.find(query).to_list(2000)
        totals = pricing.totals(lines, state, quote.get("freight") if group is None else None)
        out.append(
            {
                "name": group,
                "label": group or "Base bid",
                "isBase": group is None,
                "lineItemCount": await db.line_items.count_documents(query),
                "quoteLineCount": len(lines),
                "subtotal": totals["subtotal"],
                "grandTotal": totals["grandTotal"],
                "unpricedLines": totals["unpricedLines"],
            }
        )

    return {"alternates": out, "pending": PENDING_NOTE}


@router.post("/alternates", status_code=201)
async def create_alternate(code: str, body: AlternateCreate, actor: Actor) -> dict:
    project = await load(code)
    name = body.name.strip()

    if name in (project.get("alternates") or []):
        raise HTTPException(409, f"{name} already exists on this bid")

    await db.projects.update_one(
        {"_id": project["_id"]},
        {"$addToSet": {"alternates": name}, "$set": {"updatedAt": _now()}},
    )
    await audit.record("alternate.create", actor, {"projectId": project["_id"]}, after=name)
    return {
        "name": name,
        "label": name,
        "isBase": False,
        "lineItemCount": 0,
        "quoteLineCount": 0,
        "note": "Empty. Move lines into it, or add them by hand. " + PENDING_NOTE,
    }


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
    collection = db.line_items if scope == "line-items" else db.quote_lines
    object_ids = [oid(i) for i in line_ids]

    now = _now()
    result = await collection.update_many(
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
