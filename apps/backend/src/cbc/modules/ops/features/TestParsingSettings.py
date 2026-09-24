"""POST /api/settings/parsing/test - parse a one-page sample against on-screen values.

The sample is generated here, so its text positions are known. That is what makes
`verified` meaningful: it reports the share of returned boxes that land on text
actually on the page, measured by the same checker the pipeline uses. A frame or
orientation regression shows up on the Settings screen before a single bid is
parsed, rather than as a highlight in the wrong corner weeks later.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import fitz
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import llamaparse, page_blocks, parsing_config
from cbc.modules.ops.features.ParsingSettings import load_config
from cbc.shared.auth import require_admin

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)]
)


class ParsingTestBody(BaseModel):
    """Optional on-screen values; when omitted, saved settings are tested."""

    apiKey: str | None = None
    tier: str | None = None
    lang: str | None = None
    windowPages: int | None = Field(default=None, ge=1, le=200)
    windowTimeoutSeconds: int | None = Field(default=None, ge=60, le=7200)
    waitMaxSeconds: int | None = Field(default=None, ge=60, le=7200)


def _sample_pdf(path: Path) -> None:
    """One page: heading, paragraph, small table - enough to return blocks."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "CBC Parser Test Page", fontsize=18)
    page.insert_text((72, 110), "Sample paragraph for block extraction.", fontsize=11)
    page.insert_text((72, 160), "Item    Qty    Size", fontsize=11)
    page.insert_text((72, 180), "Door    1      3070", fontsize=11)
    page.insert_text((72, 200), "Frame   1      3070", fontsize=11)
    doc.save(path)
    doc.close()


def _classify_failure(exc: Exception) -> str:
    """Turn the client's error split into something an operator can act on."""
    text = str(exc)
    if isinstance(exc, llamaparse.ParsePermanent):
        lowered = text.lower()
        if "401" in text or "403" in text or "not authenticated" in lowered:
            return "The API key was rejected. Check PARSER_API_KEY."
        if "tier" in lowered:
            return text
        return f"Rejected and not worth retrying: {text}"
    if isinstance(exc, llamaparse.ParseRetryable):
        return f"Transient - a real job would retry: {text}"
    return text


@router.post("/parsing/test")
async def test_parsing_settings(body: ParsingTestBody | None = None) -> dict[str, Any]:
    stored = await load_config()
    typed = {k: v for k, v in (body.model_dump() if body else {}).items() if v is not None}
    resolved, _ = parsing_config.resolve({**stored, **typed}, prefer_config=True)

    problems = parsing_config.validate(resolved)
    if problems:
        raise HTTPException(400, "; ".join(problems))

    api_key = str(resolved.get("apiKey") or "").strip()
    if not api_key:
        return {"ok": False, "error": "PARSER_API_KEY is empty - parsing is off"}

    tier = str(resolved.get("tier") or parsing_config.DEFAULT_TIER)
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "cbc_parser_test.pdf"
        _sample_pdf(sample)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=300.0)) as client:
                file_id = await llamaparse.upload(client, api_key=api_key, path=sample)
                pages = await llamaparse.parse_window(
                    client,
                    api_key=api_key,
                    file_id=file_id,
                    start_page=1,
                    end_page=1,
                    tier=tier,
                    timeout=300.0,
                )
        except Exception as exc:  # reported, never raised at the operator
            return {
                "ok": False,
                "seconds": round(time.monotonic() - started, 2),
                "tier": tier,
                "error": _classify_failure(exc),
            }

        rows = page_blocks.normalise_window(
            pages,
            pdf_path=sample,
            project_id=None,
            document_id=None,
            content_sha="",
            parser={"name": "llamaparse", "tier": tier},
        )

    blocks = sum(len(r.get("blocks") or []) for r in rows)
    verified = rows[0].get("verified") if rows else None
    return {
        "ok": bool(blocks),
        "seconds": round(time.monotonic() - started, 2),
        "tier": tier,
        "blocks": blocks,
        # Share of boxes sitting on real text. None means the sample had no text
        # layer to score against, which should not happen for a generated page.
        "verified": verified,
        "error": None if blocks else "Parsed, but returned no blocks",
    }
