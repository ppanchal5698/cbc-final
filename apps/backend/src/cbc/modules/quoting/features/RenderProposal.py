"""GET /api/projects/{code}/proposal/render - the customer-facing HTML.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.proposal_view import proposal_payload, render_html

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


@router.get("/render", response_class=HTMLResponse)
async def render_proposal(code: str, autoprint: bool = False) -> HTMLResponse:
    """Render the customer-facing HTML from the shared Jinja template.

    autoprint opens the browser print dialog, which is the fallback path to a PDF
    when no local renderer is installed.
    """
    project = await load(code)
    data = await proposal_payload(project)
    html = await asyncio.to_thread(render_html, project, data, autoprint)
    return HTMLResponse(html)
