"""GET /api/projects/{code}/proposal - the proposal as rendered, with its readiness.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.proposal_view import proposal_payload

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


@router.get("")
async def get_proposal(code: str) -> dict[str, Any]:
    return await proposal_payload(await load(code))
