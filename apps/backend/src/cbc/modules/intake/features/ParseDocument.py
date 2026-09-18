"""parse_document job: send one uploaded PDF through MinerU in page windows."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from cbc.modules.intake.api import mineru as mineru_api
from cbc.modules.intake.infrastructure.collections import document_pages, documents
from cbc.modules.ops.api import parsing_config, worker
from cbc.shared import storage
from cbc.shared.mongo import oid

log = logging.getLogger("cbc.parse_document")

POLL_SECONDS = 3


class ParseRetryable(RuntimeError):
    """MinerU is down or the window timed out — burn a retry."""


class ParsePermanent(RuntimeError):
    """Bad PDF / bad settings — do not retry."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_settings() -> dict[str, Any]:
    return await parsing_config.load_stored()


async def _set_parse(document_id: Any, **fields: Any) -> None:
    await documents().update_one({"_id": document_id}, {"$set": {f"parse.{k}": v for k, v in fields.items()}})


async def after_finish(job: dict[str, Any], status: str, error: str | None, job_log) -> None:
    """Mark the document parse state when the job ends for good."""
    payload = job.get("payload") or {}
    document_id = payload.get("documentId")
    if not document_id:
        return
    oid_id = oid(document_id)
    if status == "done":
        await _set_parse(oid_id, state="parsed", error=None, finishedAt=_now())
        await _update_parse_status_file(oid_id, "parsed", error=None)
        return
    if status in {"dead", "cancelled"}:
        await _set_parse(
            oid_id,
            state="failed",
            error=error or status,
            finishedAt=_now(),
        )
        await _update_parse_status_file(oid_id, "failed", error=error or status)


async def _update_parse_status_file(
    document_id: Any, state: str, *, error: str | None
) -> None:
    """Keep extracted/_parse_status.json in sync for derive_flags (no intake→extraction import)."""
    doc = await documents().find_one({"_id": document_id})
    if doc is None:
        return
    try:
        slug = await _project_slug(doc["projectId"])
    except ParsePermanent:
        return
    path = storage.project_dir(slug) / "extracted" / "_parse_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"documents": []}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"documents": []}
    docs = [
        d
        for d in (payload.get("documents") or [])
        if isinstance(d, dict) and d.get("documentId") != str(document_id)
    ]
    docs.append(
        {
            "documentId": str(document_id),
            "filename": doc.get("filename"),
            "state": state,
            "error": error,
        }
    )
    payload["documents"] = docs
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def parse_document(job: dict[str, Any]) -> str:
    """Parse one document through MinerU; upsert documentPages per window."""
    payload = job.get("payload") or {}
    document_id = payload.get("documentId")
    if not document_id:
        raise ParsePermanent("parse_document job has no payload.documentId")

    doc = await documents().find_one({"_id": oid(document_id)})
    if doc is None:
        raise ParsePermanent(f"document {document_id} no longer exists")

    resolved = await _load_settings()
    base_url = str(resolved.get("url") or "").strip()
    if not base_url:
        raise ParsePermanent("PARSER_URL is empty — parsing is off")

    path = storage.absolute(doc["path"])
    if not path.exists():
        raise ParsePermanent(f"PDF missing on disk: {doc.get('filename')}")

    pages = int(doc.get("pages") or 0)
    if pages < 1:
        raise ParsePermanent("document has no pages")

    parser_meta = {
        "name": "mineru",
        "version": None,
        "backend": resolved.get("backend"),
        "effort": resolved.get("effort"),
    }
    await _set_parse(
        doc["_id"],
        state="running",
        pages=pages,
        pagesDone=0,
        settings={
            k: resolved.get(k)
            for k in (
                "profile",
                "backend",
                "effort",
                "method",
                "lang",
                "tables",
                "formulas",
                "imageAnalysis",
                "windowPages",
            )
        },
        error=None,
        startedAt=_now(),
    )

    window = max(1, int(resolved.get("windowPages") or 8))
    timeout = float(resolved.get("windowTimeoutSeconds") or 1800)
    task_base = parsing_config.mineru_task_body(resolved)

    # processed/mineru/{docId}/ under the project's uploads
    project = await _project_slug(doc["projectId"])
    out_dir = storage.project_dir(project) / "uploads" / "processed" / "mineru" / str(doc["_id"])
    out_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=timeout)) as client:
        # Health check — retryable when down.
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
            # Skip windows already stored for this contentSha (retry).
            existing = await document_pages().count_documents(
                {
                    "documentId": doc["_id"],
                    "contentSha": doc.get("contentSha"),
                    "page": {"$gte": start, "$lte": end},
                }
            )
            if existing >= (end - start + 1):
                pages_done = end
                await _set_parse(doc["_id"], pagesDone=pages_done)
                continue

            middle = await _parse_window(
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
                project_id=doc["projectId"],
                document_id=doc["_id"],
                content_sha=doc.get("contentSha") or "",
                parser=parser_meta,
            )
            if not rows:
                raise ParseRetryable(
                    f"MinerU window {start}-{end} normalised to 0 pages — "
                    "refusing to mark progress (likely a status stub)"
                )
            for row in rows:
                await document_pages().update_one(
                    {"documentId": doc["_id"], "page": row["page"]},
                    {"$set": row},
                    upsert=True,
                )
            pages_done = end
            await _set_parse(doc["_id"], pagesDone=pages_done)

    return f"parsed {pages_done}/{pages} pages ({parser_meta['backend']})"


async def _project_slug(project_id: Any) -> str:
    from cbc.modules.projects.api import lookup

    project = await lookup.get(project_id)
    if project is None:
        raise ParsePermanent("project no longer exists")
    return project["slug"]


async def _parse_window(
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
        "start_page_id": start_page - 1,  # MinerU is 0-based
        "end_page_id": end_page - 1,
    }
    # Flatten for multipart form
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
            raise ParsePermanent(f"MinerU rejected window {start_page}-{end_page}: {response.text[:400]}")
        response.raise_for_status()
        task = response.json()
    except ParsePermanent:
        raise
    except Exception as exc:
        raise ParseRetryable(f"MinerU task create failed: {exc}") from exc

    task_id = task.get("task_id") or task.get("id") or task.get("data", {}).get("task_id")
    if not task_id:
        # Some builds return the result inline.
        if task.get("middle_json") or task.get("pdf_info"):
            return task
        raise ParseRetryable(f"MinerU returned no task_id: {list(task)[:8]}")

    deadline = time.monotonic() + timeout
    while True:
        if await worker.job_cancelled(job_id):
            raise ParsePermanent("cancelled by estimator")
        if time.monotonic() > deadline:
            raise ParseRetryable(f"MinerU window {start_page}-{end_page} timed out after {timeout}s")
        await asyncio.sleep(POLL_SECONDS)
        try:
            status_resp = await client.get(f"{base_url.rstrip('/')}/tasks/{task_id}")
            status_resp.raise_for_status()
            body = status_resp.json()
        except Exception as exc:
            raise ParseRetryable(f"MinerU poll failed: {exc}") from exc

        state = (body.get("status") or body.get("state") or "").lower()
        if state in {"pending", "running", "processing", "queued", ""}:
            # Also check nested data.status
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
        # Unknown terminal — try to use body as result
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
