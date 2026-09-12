"""Catalog indexing jobs.

These run on the existing queue rather than a new one, which means they inherit
everything that was built for it: atomic claim, heartbeats, a reaper for a worker
that died mid-job, exponential backoff, permanent-vs-transient failure
classification, cancellation and an audit trail. A second queue would be the same
machinery again, with its own bugs.

The worker is the **only** writer to the page index. The API reads it with the
application credential and a run reads it with one that cannot write.

Indexing describes pages; it does not extract prices. A 744-page book takes
seconds because the work is string handling over text already on the page, and
because an unchanged file is not re-read at all.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.config import settings
from cbc.db import db, oid
from cbc.pageindex import build as pageindex_build
from cbc.pageindex import store as pageindex_store

log = logging.getLogger("cbc.worker.catalog")


class IndexingError(RuntimeError):
    """The file cannot be indexed, and retrying reads the same file.

    Kept as a named type because the worker classifies it as permanent: a corrupt
    PDF or a sheet with no text layer fails identically on the third attempt, and
    spending the attempt budget to reach the same answer more slowly helps nobody.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _vendor_for(book: dict[str, Any] | None, filename: str) -> str:
    """The vendor a file belongs to, from the price-book record or its name."""
    if book and book.get("vendor"):
        return str(book["vendor"]).strip().lower()
    return filename.split("_")[0].lower() or "unknown"


def _resolve(filename: str) -> Path:
    """A path inside the price-book directory, from an untrusted job payload."""
    from cbc.services import storage

    safe = storage.safe_name(str(filename))
    path = (settings.pricebook_dir / safe).resolve()
    if not path.is_relative_to(settings.pricebook_dir.resolve()):
        raise ValueError(f"catalog file must be inside {settings.pricebook_dir}: {filename!r}")
    return path


async def index_catalog(job: dict[str, Any]) -> str:
    """Describe one catalog's pages into the index."""
    payload = job.get("payload") or {}
    filename = payload.get("filename")
    if not filename:
        raise ValueError("index_catalog job has no payload.filename")

    path = _resolve(filename)
    if not path.exists():
        raise IndexingError(f"catalog file is missing: {path.name}")

    book = None
    if payload.get("priceBookId"):
        book = await db.price_books.find_one({"_id": oid(payload["priceBookId"])})

    vendor = _vendor_for(book, path.name)
    # `build_one` puts the page reading on a thread itself - a 744-page PDF would
    # otherwise stall the heartbeat and the cancel watcher - and keeps the Mongo
    # write on this loop, where the client belongs.
    document = await pageindex_build.build_one(
        path,
        vendor=vendor,
        kind=(book or {}).get("kind"),
        effective_date=(book or {}).get("effective"),
        force=bool(payload.get("force")),
    )

    if document is None:
        if book:
            await db.price_books.update_one(
                {"_id": book["_id"]}, {"$set": {"indexStatus": "ready", "updatedAt": _now()}}
            )
        return "unchanged since the last index - its pages are already described"

    if book:
        await db.price_books.update_one(
            {"_id": book["_id"]},
            {
                "$set": {
                    "catalogId": document.catalog_id,
                    "indexStatus": document.status,
                    "pageCount": document.page_count,
                    "priceBasis": document.price_basis,
                    "updatedAt": _now(),
                }
            },
        )

    weak = sum(1 for page in document.pages if page.confidence < 0.5)
    return (
        f"{document.page_count} page(s) described from {document.file_name}"
        + (f"; {weak} could not be read confidently" if weak else "")
    )


async def delete_catalog(job: dict[str, Any]) -> str:
    """Remove a catalog's index when its file is deleted.

    Nothing outlives the PDF it describes: a page description for a sheet that is
    gone would route a pricing pass at a file nobody can open.
    """
    payload = job.get("payload") or {}
    catalog_id = payload.get("catalogId")
    filename = payload.get("filename")
    if not catalog_id and not filename:
        raise ValueError("delete_catalog job needs payload.catalogId or payload.filename")

    removed = 0
    if catalog_id:
        removed += int(await pageindex_store.delete(str(catalog_id)))
    if not removed and filename:
        removed += await pageindex_store.delete_by_file(str(filename))

    if payload.get("priceBookId"):
        await db.price_books.update_one(
            {"_id": oid(payload["priceBookId"])},
            {"$set": {"catalogId": None, "indexStatus": "removed", "updatedAt": _now()}},
        )

    # Verified rather than assumed - the point of doing this on the queue.
    still_there = bool(catalog_id and await pageindex_store.get(str(catalog_id)))
    if still_there:
        raise RuntimeError(f"{catalog_id} is still in the page index after deletion")

    return f"{removed} catalog index/indexes removed" if removed else "nothing was indexed for it"
