"""Shared MinerU window parse for pricebooks and multiplier PDFs."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from cbc.modules.ops.api import mineru_blocks as mineru_api
from cbc.modules.ops.api import parsing_config, worker

log = logging.getLogger("cbc.catalog_parse")

POLL_SECONDS = 3


class ParseRetryable(RuntimeError):
    """MinerU is down or the window timed out — burn a retry."""


class ParsePermanent(RuntimeError):
    """Bad PDF / bad settings — do not retry."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_settings() -> dict[str, Any]:
    return await parsing_config.load_stored()


def page_count(path: Path) -> int:
    import fitz

    doc = fitz.open(path)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


async def parse_window(
    client: httpx.AsyncClient,
    base_url: str,
    path: Path,
    *,
    start_page: int,
    end_page: int,
    task_base: dict[str, Any],
    timeout: float,
    job_id: Any,
) -> dict[str, Any]:
    """POST /tasks for one window, poll until done, return middle JSON payload."""
    data = {
        **task_base,
        "start_page_id": start_page - 1,
        "end_page_id": end_page - 1,
    }
    form: dict[str, Any] = {}
    for key, value in data.items():
        if key == "lang_list" and isinstance(value, list):
            form["lang_list"] = value[0] if value else "en"
        elif isinstance(value, bool):
            form[key] = str(value).lower()
        else:
            form[key] = value

    try:
        with path.open("rb") as handle:
            response = await client.post(
                f"{base_url.rstrip('/')}/tasks",
                files={"files": (path.name, handle, "application/pdf")},
                data=form,
            )
        if response.status_code == 400:
            raise ParsePermanent(
                f"MinerU rejected window {start_page}-{end_page}: {response.text[:400]}"
            )
        response.raise_for_status()
        task = response.json()
    except ParsePermanent:
        raise
    except Exception as exc:
        raise ParseRetryable(f"MinerU task create failed: {exc}") from exc

    task_id = task.get("task_id") or task.get("id") or task.get("data", {}).get("task_id")
    if not task_id:
        if task.get("middle_json") or task.get("pdf_info"):
            return task
        raise ParseRetryable(f"MinerU returned no task_id: {list(task)[:8]}")

    deadline = time.monotonic() + timeout
    while True:
        if await worker.job_cancelled(job_id):
            raise ParsePermanent("cancelled by estimator")
        if time.monotonic() > deadline:
            raise ParseRetryable(
                f"MinerU window {start_page}-{end_page} timed out after {timeout}s"
            )
        await asyncio.sleep(POLL_SECONDS)
        try:
            status_resp = await client.get(f"{base_url.rstrip('/')}/tasks/{task_id}")
            status_resp.raise_for_status()
            body = status_resp.json()
        except Exception as exc:
            raise ParseRetryable(f"MinerU poll failed: {exc}") from exc

        state = (body.get("status") or body.get("state") or "").lower()
        if state in {"pending", "running", "processing", "queued", ""}:
            nested = body.get("data") if isinstance(body.get("data"), dict) else {}
            state = (nested.get("status") or state).lower()
            if state in {"pending", "running", "processing", "queued", ""}:
                continue
        if state in {"failed", "error"}:
            err = body.get("error") or body.get("message") or body
            raise ParseRetryable(f"MinerU task failed: {err}")
        if state in {"done", "completed", "success"}:
            return await _completed_middle(
                client,
                body,
                start_page=start_page,
                end_page=end_page,
            )
        if body.get("middle_json") or body.get("pdf_info") or (
            isinstance(body.get("data"), dict) and body["data"].get("middle_json")
        ):
            return body.get("data") if isinstance(body.get("data"), dict) else body
        continue


async def _completed_middle(
    client: httpx.AsyncClient,
    body: dict[str, Any],
    *,
    start_page: int,
    end_page: int,
) -> dict[str, Any]:
    """Resolve a completed MinerU task to real middle JSON (never a status stub)."""
    candidate: Any = body.get("result")
    if not isinstance(candidate, dict):
        data = body.get("data")
        candidate = data if isinstance(data, dict) else body

    candidate = mineru_api.unwrap_mineru_payload(candidate)
    if mineru_api.looks_like_middle(candidate):
        return candidate if isinstance(candidate, dict) else {"pdf_info": candidate}

    result_url = None
    if isinstance(candidate, dict):
        result_url = candidate.get("result_url")
    if not result_url:
        result_url = body.get("result_url")
    data = body.get("data")
    if not result_url and isinstance(data, dict):
        result_url = data.get("result_url")

    if result_url:
        try:
            resp = await client.get(str(result_url))
            resp.raise_for_status()
            fetched = mineru_api.unwrap_mineru_payload(resp.json())
        except Exception as exc:
            raise ParseRetryable(
                f"MinerU result_url fetch failed for window {start_page}-{end_page}: {exc}"
            ) from exc
        if isinstance(fetched, dict) and mineru_api.looks_like_middle(fetched):
            return fetched
        if isinstance(fetched, list) and mineru_api.looks_like_middle(fetched):
            return {"pdf_info": fetched}
        raise ParseRetryable(
            f"MinerU result_url for window {start_page}-{end_page} had no page content"
        )

    raise ParseRetryable(
        f"MinerU completed window {start_page}-{end_page} with a status stub "
        "(no middle_json/pdf_info and no result_url)"
    )


async def run_windows(
    *,
    job: dict[str, Any],
    path: Path,
    pages: int,
    content_sha: str,
    out_dir: Path,
    on_rows,
    set_progress,
) -> tuple[int, dict[str, Any]]:
    """Parse every window; call on_rows(rows) after normalise; set_progress(pages_done)."""
    resolved = await load_settings()
    base_url = str(resolved.get("url") or "").strip()
    if not base_url:
        raise ParsePermanent("PARSER_URL is empty — parsing is off")

    parser_meta = {
        "name": "mineru",
        "version": None,
        "backend": resolved.get("backend"),
        "effort": resolved.get("effort"),
    }
    window = max(1, int(resolved.get("windowPages") or 8))
    timeout = float(resolved.get("windowTimeoutSeconds") or 1800)
    task_base = parsing_config.mineru_task_body(resolved)
    out_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=timeout)) as client:
        try:
            health = await client.get(f"{base_url.rstrip('/')}/health")
            health.raise_for_status()
            parser_meta["version"] = (health.json() or {}).get("version")
        except Exception as exc:
            raise ParseRetryable(f"MinerU unreachable: {exc}") from exc

        pages_done = 0
        for start in range(1, pages + 1, window):
            if await worker.job_cancelled(job["_id"]):
                raise ParsePermanent("cancelled by estimator")
            end = min(start + window - 1, pages)
            middle = await parse_window(
                client,
                base_url,
                path,
                start_page=start,
                end_page=end,
                task_base=task_base,
                timeout=timeout,
                job_id=job["_id"],
            )
            raw_path = out_dir / f"p{start}-{end}.json"
            raw_path.write_text(json.dumps(middle), encoding="utf-8")

            rows = await asyncio.to_thread(
                mineru_api.normalise_window,
                middle,
                pdf_path=path,
                start_page=start,
                project_id=None,
                document_id=None,
                content_sha=content_sha,
                parser=parser_meta,
            )
            if not rows:
                raise ParseRetryable(
                    f"MinerU window {start}-{end} normalised to 0 pages — "
                    "refusing to mark progress (likely a status stub)"
                )
            await on_rows(rows, start=start, end=end)
            pages_done = end
            await set_progress(pages_done)

    return pages_done, parser_meta


def remap_blocks(
    rows: list[dict[str, Any]],
    *,
    extras: dict[str, Any],
) -> list[dict[str, Any]]:
    """Drop bid documentPages keys; attach catalog/multiplier identity fields."""
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                **extras,
                "contentSha": row.get("contentSha"),
                "page": row["page"],
                "pageSize": row.get("pageSize"),
                "blocks": row.get("blocks") or [],
                "verified": row.get("verified"),
                "parser": row.get("parser"),
                "parsedAt": row.get("parsedAt") or _now(),
            }
        )
    return out
