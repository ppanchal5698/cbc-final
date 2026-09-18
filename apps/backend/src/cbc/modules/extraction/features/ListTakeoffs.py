"""GET /api/projects/{code}/takeoffs - FRP geometry recorded against a bid (FR-12).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.infrastructure.collections import takeoffs
from cbc.modules.projects.api.lookup import load
from cbc.shared import storage
from cbc.shared.mongo import serialise
from cbc.shared.pass_files import read_json

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


def _scope_flags(slug: str) -> dict[str, Any]:
    summary = read_json(storage.project_dir(slug) / "extracted" / "scope_summary.json")
    if not isinstance(summary, dict):
        return {"frpInScope": False, "div10InScope": False}
    return {
        "frpInScope": bool(summary.get("frp_in_scope")),
        "div10InScope": bool(summary.get("div10_in_scope")),
    }


@router.get("/takeoffs")
async def list_takeoffs(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await takeoffs().find({"bidRequestId": project["_id"]}).to_list(100)
    return {"takeoffs": serialise(rows), **_scope_flags(project["slug"])}