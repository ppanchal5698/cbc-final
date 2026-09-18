"""parse_catalog job: MinerU windows → catalogPages for one price book PDF."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.modules.catalog.api import catalog_parse
from cbc.modules.catalog.api.pageindex import query as page_query
from cbc.modules.catalog.api.pageindex import store as catalog_store
from cbc.modules.catalog.infrastructure.collections import catalog_pages, price_books
from cbc.modules.ops.api import parsing_config, worker
from cbc.shared import storage
from cbc.shared.config import settings
from cbc.shared.mongo import oid

log = logging.getLogger("cbc.parse_catalog")

ParseRetryable = catalog_parse.ParseRetryable
ParsePermanent = catalog_parse.ParsePermanent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve(filename: str) -> Path:
    safe = storage.safe_name(str(filename))
    path = (settings.pricebook_dir / safe).resolve()
    if not path.is_relative_to(settings.pricebook_dir.resolve()):
        raise ParsePermanent(
            f"catalog file must be inside {settings.pricebook_dir}: {filename!r}"
        )
    return path


async def _set_parse(book_id: Any, **fields: Any) -> None:
    await price_books().update_one(
        {"_id": book_id},
        {
            "$set": {
                **{f"parse.{k}": v for k, v in fields.items()},
                "updatedAt": _now(),
            }
        },
    )


async def after_finish(job: dict[str, Any], status: str, error: str | None, job_log) -> None:
    payload = job.get("payload") or {}
    book_id = payload.get("priceBookId")
    if not book_id:
        return
    oid_id = oid(book_id)
    if status == "done":
        await _set_parse(oid_id, state="parsed", error=None, finishedAt=_now())
        return
    if status in {"dead", "cancelled"}:
        await _set_parse(oid_id, state="failed", error=error or status, finishedAt=_now())


def artefact_dir(price_book_id: Any) -> Path:
    return settings.pricebook_dir / "processed" / "mineru" / str(price_book_id)


async def purge_pages(
    *, price_book_id: str | None = None, catalog_id: str | None = None
) -> int:
    """Delete catalogPages (+ artefacts) for a book."""
    filt: dict[str, Any] = {}
    if price_book_id:
        filt["priceBookId"] = oid(price_book_id)
    elif catalog_id:
        filt["catalogId"] = catalog_id
    else:
        return 0
    result = await catalog_pages().delete_many(filt)
    if price_book_id:
        out = artefact_dir(price_book_id)
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)
    return int(result.deleted_count)


async def parse_catalog(job: dict[str, Any]) -> str:
    """Parse one price book through MinerU; upsert catalogPages per window."""
    payload = job.get("payload") or {}
    book_id = payload.get("priceBookId")
    filename = payload.get("filename")
    if not book_id and not filename:
        raise ParsePermanent("parse_catalog needs payload.priceBookId or payload.filename")

    book = None
    if book_id:
        book = await price_books().find_one({"_id": oid(book_id)})
        if book is None:
            raise ParsePermanent(f"price book {book_id} no longer exists")
        filename = filename or book.get("filename")

    if not filename:
        raise ParsePermanent("parse_catalog: book has no filename")

    path = _resolve(filename)
    if not path.exists():
        raise ParsePermanent(f"PDF missing on disk: {filename}")

    resolved = await catalog_parse.load_settings()
    if not parsing_config.enabled(resolved):
        raise ParsePermanent("PARSER_URL is empty — parsing is off")

    content_sha = payload.get("fileSha") or catalog_store.file_hash(path)
    catalog_id = (
        (book or {}).get("catalogId")
        or payload.get("catalogId")
        or catalog_store.catalog_id_for(path.name)
    )
    vendor = str(
        (book or {}).get("vendor") or path.name.split("_")[0] or "unknown"
    ).strip().lower()
    pages = catalog_parse.page_count(path)
    if pages < 1:
        raise ParsePermanent("price book has no pages")

    book_oid = (book or {}).get("_id") or oid(book_id)
    await _set_parse(
        book_oid,
        state="running",
        pages=pages,
        pagesDone=0,
        catalogId=catalog_id,
        error=None,
        startedAt=_now(),
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
    )

    file_path = f"{page_query.PRICEBOOK_DIR}/{path.name}"
    out_dir = artefact_dir(book_oid)
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

    import asyncio
    import json

    import httpx

    from cbc.modules.ops.api import mineru_blocks as mineru_api

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
            existing = await catalog_pages().count_documents(
                {
                    "priceBookId": book_oid,
                    "contentSha": content_sha,
                    "page": {"$gte": start, "$lte": end},
                }
            )
            if existing >= (end - start + 1):
                pages_done = end
                await _set_parse(book_oid, pagesDone=pages_done)
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
                    "priceBookId": book_oid,
                    "catalogId": catalog_id,
                    "vendor": vendor,
                    "filename": path.name,
                    "filePath": file_path,
                },
            )
            for row in remapped:
                await catalog_pages().update_one(
                    {"priceBookId": book_oid, "page": row["page"]},
                    {"$set": row},
                    upsert=True,
                )
            pages_done = end
            await _set_parse(book_oid, pagesDone=pages_done)

    return f"parsed {pages_done}/{pages} pages ({parser_meta['backend']})"
