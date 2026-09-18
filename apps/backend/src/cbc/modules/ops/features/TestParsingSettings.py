"""POST /api/settings/parsing/test - parse a one-page sample against on-screen values."""
from __future__ import annotations

import time
from typing import Any

import fitz
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import parsing_config
from cbc.modules.ops.features.ParsingSettings import load_config
from cbc.shared.auth import require_admin

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)]
)


class ParsingTestBody(BaseModel):
    """Optional on-screen values; when omitted, saved settings are tested."""

    url: str | None = None
    profile: str | None = None
    backend: str | None = None
    effort: str | None = None
    method: str | None = None
    lang: str | None = None
    tables: bool | None = None
    formulas: bool | None = None
    imageAnalysis: bool | None = None
    windowPages: int | None = Field(default=None, ge=1, le=200)
    windowTimeoutSeconds: int | None = Field(default=None, ge=60, le=7200)
    waitMaxSeconds: int | None = Field(default=None, ge=60, le=7200)


def _sample_pdf() -> bytes:
    """One page: heading, paragraph, small table — enough for MinerU to return blocks."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "CBC Parser Test Page", fontsize=18)
    page.insert_text(
        (72, 110),
        "Sample paragraph for MinerU block extraction.",
        fontsize=11,
    )
    # Simple table-like lines
    page.insert_text((72, 160), "Item    Qty    Size", fontsize=11)
    page.insert_text((72, 180), "Door    1      3070", fontsize=11)
    page.insert_text((72, 200), "Frame   1      3070", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _classify_failure(exc: Exception, response: httpx.Response | None) -> str:
    text = str(exc)
    if response is not None:
        body = ""
        try:
            body = response.text[:500]
        except Exception:
            body = ""
        if response.status_code == 400:
            return f"MinerU rejected the request (400): {body or text}"
        if "model" in body.lower() or "not found" in body.lower():
            return (
                "MinerU reported missing models. Start the matching profile "
                "(infra/mineru/low.env, medium.env, or high.env) and rebuild."
            )
        return f"MinerU HTTP {response.status_code}: {body or text}"
    lowered = text.lower()
    if "connect" in lowered or "unreachable" in lowered or "name or service" in lowered:
        return f"MinerU unreachable: {text}"
    return text


@router.post("/parsing/test")
async def test_parsing_settings(body: ParsingTestBody | None = None) -> dict[str, Any]:
    """Build a one-page PDF and POST it to MinerU /file_parse with on-screen values."""
    stored = await load_config()
    typed = body is not None
    candidate = dict(stored)
    if body is not None:
        for key, value in body.model_dump(exclude_none=True).items():
            candidate[key] = value

    resolved, _ = parsing_config.resolve(candidate, prefer_config=typed)
    problems = parsing_config.validate(resolved)
    if problems:
        raise HTTPException(400, "; ".join(problems))

    url = str(resolved.get("url") or "").strip()
    if not url:
        return {
            "ok": False,
            "error": "PARSER_URL is empty — turn parsing on before testing",
            "seconds": None,
            "blocks": None,
            "version": None,
        }

    pdf_bytes = _sample_pdf()
    task_fields = parsing_config.mineru_task_body(resolved)
    # /file_parse is the sync convenience endpoint for a single file.
    started = time.perf_counter()
    response: httpx.Response | None = None
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            files = {"files": ("sample.pdf", pdf_bytes, "application/pdf")}
            data = {k: str(v).lower() if isinstance(v, bool) else v for k, v in task_fields.items()}
            # lang_list is a list — MinerU expects repeated form fields or JSON.
            data.pop("lang_list", None)
            data["lang_list"] = resolved.get("lang") or "en"
            response = await client.post(
                f"{url.rstrip('/')}/file_parse",
                files=files,
                data=data,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "ok": False,
            "error": _classify_failure(exc, response),
            "seconds": round(time.perf_counter() - started, 2),
            "blocks": None,
            "version": None,
        }

    elapsed = round(time.perf_counter() - started, 2)
    blocks = _count_blocks(payload)
    version = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(f"{url.rstrip('/')}/health")
            if health.is_success:
                version = (health.json() or {}).get("version")
    except Exception:
        pass

    return {
        "ok": True,
        "seconds": elapsed,
        "blocks": blocks,
        "version": version,
        "backend": resolved.get("backend"),
        "error": None,
    }


def _count_blocks(payload: dict[str, Any]) -> int:
    """Best-effort block count across MinerU response shapes."""
    middle = payload.get("middle_json") or payload.get("results") or payload
    if isinstance(middle, str):
        import json

        try:
            middle = json.loads(middle)
        except json.JSONDecodeError:
            return 0
    if isinstance(middle, list):
        return sum(_count_blocks(item) if isinstance(item, dict) else 0 for item in middle)
    if not isinstance(middle, dict):
        return 0
    pages = middle.get("pdf_info") or middle.get("pages") or []
    if isinstance(pages, dict):
        pages = list(pages.values())
    total = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        for key in ("para_blocks", "preproc_blocks", "discarded_blocks", "blocks"):
            blocks = page.get(key)
            if isinstance(blocks, list):
                total += len(blocks)
    return total
