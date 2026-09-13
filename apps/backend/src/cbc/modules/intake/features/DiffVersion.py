"""GET /api/projects/{code}/versions/{version}/diff - what changed since a version was frozen.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.db import db  # ponytail: openings and quote lines read directly until extraction and quoting own them (steps 3.7, 3.9)
from cbc.modules.intake.domain.versions import PENDING_NOTE
from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.projects.api.lookup import load

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


@router.get("/versions/{version}/diff")
async def diff_version(code: str, version: int) -> dict[str, Any]:
    project = await load(code)
    stored = await versions().find_one({"projectId": project["_id"], "version": version})
    if not stored:
        raise HTTPException(404, f"version {version} not found")

    def key(item: dict[str, Any]) -> str:
        return str(item.get("mark") or item.get("description", ""))[:60]

    before = {key(i): i for i in stored["snapshot"]["lineItems"]}
    current = {
        key(i): i for i in await db.line_items.find({"projectId": project["_id"]}).to_list(5000)
    }

    watched = ("description", "size", "qty", "hwSet", "finish", "fireRating", "handing")
    changed = []
    for mark, now in current.items():
        was = before.get(mark)
        if not was:
            continue
        fields = [f for f in watched if str(was.get(f)) != str(now.get(f))]
        if fields:
            changed.append(
                {
                    "mark": mark,
                    "fields": fields,
                    "before": {f: was.get(f) for f in fields},
                    "after": {f: now.get(f) for f in fields},
                }
            )

    return {
        "version": version,
        "added": sorted(set(current) - set(before)),
        "removed": sorted(set(before) - set(current)),
        "changed": changed,
        "pending": PENDING_NOTE,
    }
