"""GET /api/projects/{code}/proposal/pdf - the proposal as a PDF, or 501 with no local renderer.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.proposal_view import proposal_payload, render_html
from cbc.shared.config import settings

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


@router.get("/pdf")
async def proposal_pdf(code: str) -> Response:
    """Download the proposal as a PDF.

    Rendered locally - no converter is fetched from the internet. If no renderer
    is installed the caller is told plainly rather than handed a broken file.
    """
    project = await load(code)
    html = await asyncio.to_thread(render_html, project, await proposal_payload(project), False)

    try:
        from weasyprint import HTML  # type: ignore
    except Exception as exc:
        # WeasyPrint imports on Windows but fails to load its GTK libraries with
        # an OSError, so this cannot narrow to ImportError.
        raise HTTPException(
            501,
            "No working local PDF renderer. Use the printable view and print to PDF "
            "from the browser, or install the WeasyPrint native libraries (GTK "
            f"runtime on Windows). Underlying error: {exc}",
        ) from exc

    # WeasyPrint is CPU-bound and takes seconds on a long proposal; inline it
    # blocked every other request for the duration.
    pdf_bytes = await asyncio.to_thread(
        HTML(string=html, base_url=str(settings.repo_root)).write_pdf
    )
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{project["code"]}-proposal.pdf"'},
    )
