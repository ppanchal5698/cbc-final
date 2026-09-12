"""Shared project lookup used by every domain API."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from cbc.db import db, oid

STAGE_PROGRESS = {"intake": 0, "extraction": 33, "quote": 67, "proposal": 100}


async def load(code_or_id: str) -> dict[str, Any]:
    """Look a project up by code (CBC-260143), slug, or id."""
    query: dict[str, Any] = {"$or": [{"code": code_or_id}, {"slug": code_or_id}]}
    try:
        query["$or"].append({"_id": oid(code_or_id)})
    except ValueError:
        pass
    project = await db.projects.find_one(query)
    if not project:
        raise HTTPException(404, f"project not found: {code_or_id}")
    return project
