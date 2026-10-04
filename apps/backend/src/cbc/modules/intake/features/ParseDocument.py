"""parse_document job: send one uploaded PDF through LlamaParse in page windows.

The document is uploaded **once** and every window reuses the returned file_id.
The upload-and-parse endpoint would re-send the whole file per window, and a
20 MB plan set sent eleven times is the one obvious way to make a cloud parser
slower than the GPU it replaced.

A window LlamaParse cannot deliver - a permanent error, a transient one on the
last attempt, or a start after `parse.deadlineAt` - is read locally instead
(`page_blocks.local_window`), so a bid always moves on. Those pages are listed in
`parse.fallbackPages` and surface as the `parse_fallback` review flag.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from cbc.modules.intake.infrastructure.collections import document_pages, documents
from cbc.modules.ops.api import llamaparse, page_blocks, parsing_config, worker
from cbc.shared import storage
from cbc.shared.mongo import oid

log = logging.getLogger("cbc.parse_document")

# One pair of error classes for the whole parse path; re-exported here because
# `intake/__init__.py` registers the permanent set from this module.
ParseRetryable = llamaparse.ParseRetryable
ParsePermanent = llamaparse.ParsePermanent


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
    """Keep extracted/_parse_status.json in sync for derive_flags (no intakeâ†’extraction import)."""
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
            "fallbackPages": (doc.get("parse") or {}).get("fallbackPages") or [],
        }
    )
    payload["documents"] = docs
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def parse_document(job: dict[str, Any]) -> str:
    """Parse one document through LlamaParse; upsert documentPages per window."""
    payload = job.get("payload") or {}
    document_id = payload.get("documentId")
    if not document_id:
        raise ParsePermanent("parse_document job has no payload.documentId")

    doc = await documents().find_one({"_id": oid(document_id)})
    if doc is None:
        raise ParsePermanent(f"document {document_id} no longer exists")

    resolved = await _load_settings()
    api_key = str(resolved.get("apiKey") or "").strip()
    if not api_key:
        raise ParsePermanent("PARSER_API_KEY is empty — parsing is off")

    path = storage.absolute(doc["path"])
    if not path.exists():
        raise ParsePermanent(f"PDF missing on disk: {doc.get('filename')}")

    pages = int(doc.get("pages") or 0)
    if pages < 1:
        raise ParsePermanent("document has no pages")

    tier = str(resolved.get("tier") or parsing_config.DEFAULT_TIER)
    parser_meta = {"name": "llamaparse", "version": "v2", "tier": tier}
    # The deadline runs from the first attempt. A retry still finds the parse
    # `running` (after_finish only fires once the job ends for good), and
    # restarting the clock on every attempt would let three slow attempts hold
    # the bid for three times the wait the estimator configured.
    previous = doc.get("parse") or {}
    started_at = (
        previous.get("startedAt")
        if previous.get("state") == "running" and previous.get("startedAt")
        else _now()
    )
    wait_max = int(
        resolved.get("waitMaxSeconds") or parsing_config.DEFAULTS["waitMaxSeconds"]
    )
    deadline_at = started_at + timedelta(seconds=wait_max)
    # On the last attempt a transient LlamaParse error is read locally instead:
    # there is no retry left to come good on, and a dead parse holds the bid.
    last_attempt = int(job.get("attempts") or 1) >= worker.MAX_ATTEMPTS
    await _set_parse(
        doc["_id"],
        state="running",
        pages=pages,
        pagesDone=0,
        settings={k: resolved.get(k) for k in ("tier", "lang", "windowPages")},
        error=None,
        startedAt=started_at,
        deadlineAt=deadline_at,
    )

    window = max(1, int(resolved.get("windowPages") or 8))
    timeout = float(resolved.get("windowTimeoutSeconds") or 1800)

    project = await _project_slug(doc["projectId"])
    out_dir = storage.project_dir(project) / "uploads" / "processed" / "parsed" / str(doc["_id"])
    out_dir.mkdir(parents=True, exist_ok=True)

    async def cancelled() -> bool:
        return await worker.job_cancelled(job["_id"])

    async def or_local(call: Any, what: str) -> Any:
        """The LlamaParse call's result, or None when the pages should be read locally.

        A permanent error will not come good on a retry, so it falls back at
        once - except a cancel, which arrives as ParsePermanent too and must
        stop the job rather than finish it locally. A transient error keeps
        today's retry until the last attempt.
        """
        try:
            return await call
        except ParsePermanent as exc:
            if await cancelled():
                raise
            log.warning("%s failed permanently, reading locally: %s", what, exc)
        except ParseRetryable as exc:
            if not last_attempt:
                raise
            log.warning("%s failed on the last attempt, reading locally: %s", what, exc)
        return None

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=timeout)) as client:
        file_id = str((doc.get("parse") or {}).get("fileId") or "")
        if not file_id and _now() < deadline_at:
            file_id = await or_local(
                llamaparse.upload(client, api_key=api_key, path=path), "upload"
            ) or ""
            if file_id:
                # Cached so a retried or resumed job does not re-send the document.
                await _set_parse(doc["_id"], fileId=file_id)

        # Windows run concurrently. They are genuinely independent: each asks for
        # its own page range, upserts its own pages keyed by `page`, and is
        # skipped on its own already-parsed count. Sequencing them bought an
        # ordering nobody consumes.
        #
        # It cost the whole run. Measured on an 87-page set: a window spends
        # ~174s waiting on the API and ~4s in our code, so 97.7% of the elapsed
        # time was one window blocking the next, and eleven windows took 32
        # minutes to do about three minutes of work.
        #
        # The semaphore is the throttle. Unbounded fan-out would open every
        # window at once against a rate-limited API and trade a slow run for a
        # failing one.
        limit = max(1, int(resolved.get("windowConcurrency") or 4))
        gate = asyncio.Semaphore(limit)
        progress = asyncio.Lock()
        pages_done = 0

        async def run_window(start: int, end: int) -> None:
            nonlocal pages_done
            span = end - start + 1
            async with gate:
                if await cancelled():
                    raise ParsePermanent("cancelled by estimator")
                # Skip windows already stored for this contentSha (retry/resume).
                existing = await document_pages().count_documents(
                    {
                        "documentId": doc["_id"],
                        "contentSha": doc.get("contentSha"),
                        "page": {"$gte": start, "$lte": end},
                    }
                )
                if existing < span:
                    window_pages = None
                    # A window that would start after the deadline is never
                    # sent: it would wait up to its own timeout on top.
                    if file_id and _now() < deadline_at:
                        window_pages = await or_local(
                            llamaparse.parse_window(
                                client,
                                api_key=api_key,
                                file_id=file_id,
                                start_page=start,
                                end_page=end,
                                tier=tier,
                                timeout=timeout,
                                cancelled=cancelled,
                            ),
                            f"window {start}-{end}",
                        )
                    window_parser = parser_meta
                    if window_pages is None:
                        window_parser = page_blocks.LOCAL_PARSER
                        window_pages = await asyncio.to_thread(
                            lambda: [
                                page_blocks.local_window(path, p)
                                for p in range(start, end + 1)
                            ]
                        )
                    (out_dir / f"p{start}-{end}.json").write_text(
                        json.dumps(window_pages), encoding="utf-8"
                    )
                    rows = await asyncio.to_thread(
                        page_blocks.normalise_window,
                        window_pages,
                        pdf_path=path,
                        project_id=doc["projectId"],
                        document_id=doc["_id"],
                        content_sha=doc.get("contentSha") or "",
                        parser=window_parser,
                    )
                    if len(rows) != span:
                        # Every requested page must come back, even empty. A short
                        # window would mark progress over pages nothing ever read.
                        raise ParseRetryable(
                            f"window {start}-{end} normalised to {len(rows)} of "
                            f"{span} pages — refusing to mark progress"
                        )
                    for row in rows:
                        await document_pages().update_one(
                            {"documentId": doc["_id"], "page": row["page"]},
                            {"$set": row},
                            upsert=True,
                        )

            # Completion is unordered now, so pagesDone counts pages actually
            # stored rather than the end page of the last window. Reporting an
            # end page would let a fast later window claim the ones still in
            # flight, and the estimator would watch progress jump and stall.
            async with progress:
                pages_done += span
                done = pages_done
            await _set_parse(doc["_id"], pagesDone=done)

        bounds = [
            (start, min(start + window - 1, pages))
            for start in range(1, pages + 1, window)
        ]
        # Default gather: the first failure propagates and its siblings are
        # cancelled. Windows that already finished keep their upserted pages, so
        # the retry resumes from the skip check rather than starting over.
        await asyncio.gather(*(run_window(s, e) for s, e in bounds))

    # Read back from the stored pages rather than counted in this run: a window
    # read locally on an earlier attempt is skipped by this one, and is still a
    # local page.
    fallback = sorted(
        await document_pages().distinct(
            "page",
            {
                "documentId": doc["_id"],
                "contentSha": doc.get("contentSha"),
                "parser.name": page_blocks.LOCAL_PARSER["name"],
            },
        )
    )
    backend = "local" if len(fallback) >= pages else "mixed" if fallback else "llamaparse"
    await _set_parse(doc["_id"], fallbackPages=fallback, **{"settings.backend": backend})

    return f"parsed {pages_done}/{pages} pages ({tier}, {limit} at a time, {backend})"


async def _project_slug(project_id: Any) -> str:
    from cbc.modules.projects.api import lookup

    project = await lookup.get(project_id)
    if project is None:
        raise ParsePermanent("project no longer exists")
    return project["slug"]

