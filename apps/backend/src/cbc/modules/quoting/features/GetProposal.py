"""GET /api/projects/{code}/proposal - the proposal as rendered, with its readiness.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.proposal_view import export_for_review, proposal_payload

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


@router.get("")
async def get_proposal(code: str) -> dict[str, Any]:
    # Exported here as well as on approval: the screen disables Approve on
    # `readiness.blocking`, so a flag computed from stale files would hold a
    # line the estimator has already fixed with no way to press the button.
    project = await load(code)
    await export_for_review(project)
    return await proposal_payload(project)
