"""parse_multiplier job: MinerU windows → multiplierPages for a multiplier PDF."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from cbc.modules.catalog.api import catalog_parse
from cbc.modules.catalog.api.pageindex import query as page_query
from cbc.modules.catalog.api.pageindex import store as catalog_store
from cbc.modules.catalog.infrastructure.collections import multiplier_pages, price_books
from cbc.modules.ops.api import mineru_blocks as mineru_api
from cbc.modules.ops.api import parsing_config, worker
from cbc.shared import storage
from cbc.shared.config import settings
from cbc.shared.mongo import oid
from cbc.shared.paths import reference_dir

log = logging.getLogger("cbc.parse_multiplier")

ParseRetryable = catalog_parse.ParseRetryable
ParsePermanent = catalog_parse.ParsePermanent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve(filename: str, *, prefer_reference: bool = False) -> Path:
    """Multiplier PDFs usually live under pricebooks/; optional reference copy."""
    safe = storage.safe_name(str(filename))
    candidates: list[Path] = []
    if prefer_reference:
        candidates.append((reference_dir() / "multipliers" / safe).resolve())
    candidates.append((settings.pricebook_dir / safe).resolve())
    if not prefer_reference:
        candidates.append((reference_dir() / "multipliers" / safe).resolve())
    for path in candidates:
        root = path.parent
        if path.exists() and path.is_relative_to(root.resolve()):
            return path
    # Default write-side root for error messages
    return (settings.pricebook_dir / safe).resolve()


async def after_finish(job: dict[str, Any], status: str, error: str | None, job_log) -> None:
    payload = job.get("payload") or {}
    book_id = payload.get("priceBookId")
    if not book_id:
        return
    fields: dict[str, Any]
    if status == "done":
        fields = {"state": "parsed", "error": None, "finishedAt": _now()}
    elif status in {"dead", "cancelled"}:
        fields = {"state": "failed", "error": error or status, "finishedAt": _now()}
    else:
        return
    await price_books().update_one(
        {"_id": oid(book_id)},
        {
            "$set": {
                **{f"parse.{k}": v for k, v in fields.items()},
                "updatedAt": _now(),
            }
        },
    )


def artefact_dir(sheet_id: str) -> Path:
    """MinerU middle JSON for multiplier sheets.

    Must live under ``pricebooks/`` (writable in compose). ``reference-library``
    is mounted read-only — writing ``multipliers/processed`` there raises
    Errno 30 and leaves parse.state=failed.
    """
    return settings.pricebook_dir / "processed" / "mineru" / "multipliers" / str(sheet_id)


async def purge_pages(*, sheet_id: str | None = None) -> int:
    if not sheet_id:
        return 0
    result = await multiplier_pages().delete_many({"sheetId": sheet_id})
    out = artefact_dir(sheet_id)
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    return int(result.deleted_count)


async def parse_multiplier(job: dict[str, Any]) -> str:
    """Parse one multiplier PDF through MinerU; upsert multiplierPages."""
    payload = job.get("payload") or {}
    filename = payload.get("filename")
    book_id = payload.get("priceBookId")
    book = None
    if book_id:
        book = await price_books().find_one({"_id": oid(book_id)})
        if book is None:
            raise ParsePermanent(f"price book {book_id} no longer exists")
        filename = filename or book.get("filename")
    if not filename:
        raise ParsePermanent("parse_multiplier needs payload.filename")

    path = _resolve(filename)
    if not path.exists():
        raise ParsePermanent(f"PDF missing on disk: {filename}")

    resolved = await catalog_parse.load_settings()
    if not parsing_config.enabled(resolved):
        raise ParsePermanent("PARSER_URL is empty — parsing is off")

    content_sha = payload.get("fileSha") or catalog_store.file_hash(path)
    sheet_id = payload.get("sheetId") or catalog_store.catalog_id_for(path.name)
    family = payload.get("family") or (book or {}).get("vendor") or "multipliers"
    vendor = str((book or {}).get("vendor") or family).strip().lower()
    pages = catalog_parse.page_count(path)
    if pages < 1:
        raise ParsePermanent("multiplier sheet has no pages")

    if book:
        await price_books().update_one(
            {"_id": book["_id"]},
            {
                "$set": {
                    "parse.state": "running",
                    "parse.pages": pages,
                    "parse.pagesDone": 0,
                    "parse.sheetId": sheet_id,
                    "parse.error": None,
                    "parse.startedAt": _now(),
                    "updatedAt": _now(),
                }
            },
        )

    # file_path: same prefix as catalog MCP when under pricebooks/
    try:
        under_pb = path.is_relative_to(settings.pricebook_dir.resolve())
    except (ValueError, AttributeError):
        under_pb = False
    file_path = (
        f"{page_query.PRICEBOOK_DIR}/{path.name}"
        if under_pb
        else f"data/reference-library/multipliers/{path.name}"
    )

    out_dir = artefact_dir(sheet_id)
    window = max(1, int(resolved.get("windowPages") or 8))
    base_url = str(resolved.get("url") or "").strip()
    timeout = float(resolved.get("windowTimeoutSeconds") or 1800)
    task_base = parsing_config.mineru_task_body(resolved)
    parser_meta = {
        "name": "mineru",
        "version": None,
        "backend": resolved.get("backend"),
        "effort": resolved.get("effort"),
    }
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
            existing = await multiplier_pages().count_documents(
                {
                    "sheetId": sheet_id,
                    "contentSha": content_sha,
                    "page": {"$gte": start, "$lte": end},
                }
            )
            if existing >= (end - start + 1):
                pages_done = end
                if book:
                    await price_books().update_one(
                        {"_id": book["_id"]},
                        {"$set": {"parse.pagesDone": pages_done, "updatedAt": _now()}},
                    )
                continue

            middle = await catalog_parse.parse_window(
                client,
                base_url,
                path,
                start_page=start,
                end_page=end,
                task_base=task_base,
                timeout=timeout,
                job_id=job["_id"],
            )
            (out_dir / f"p{start}-{end}.json").write_text(
                json.dumps(middle), encoding="utf-8"
            )
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
            remapped = catalog_parse.remap_blocks(
                rows,
                extras={
                    "sheetId": sheet_id,
                    "family": family,
                    "vendor": vendor,
                    "filename": path.name,
                    "filePath": file_path,
                    "priceBookId": book["_id"] if book else None,
                },
            )
            for row in remapped:
                await multiplier_pages().update_one(
                    {"sheetId": sheet_id, "page": row["page"]},
                    {"$set": row},
                    upsert=True,
                )
            pages_done = end
            if book:
                await price_books().update_one(
                    {"_id": book["_id"]},
                    {"$set": {"parse.pagesDone": pages_done, "updatedAt": _now()}},
                )

    return f"parsed multiplier {pages_done}/{pages} pages ({parser_meta['backend']})"
