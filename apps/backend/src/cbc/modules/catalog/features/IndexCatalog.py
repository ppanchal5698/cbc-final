"""The index_catalog job: describe one price book's pages into the page index.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.modules.catalog.infrastructure import pricebook_reader
from cbc.modules.catalog.infrastructure.collections import price_book_entries, price_books
from cbc.modules.catalog.api.pageindex import build as pageindex_build
from cbc.modules.catalog.api.pageindex import store as catalog_store
from cbc.shared.config import settings
from cbc.shared.mongo import oid


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
    from cbc.shared import storage

    safe = storage.safe_name(str(filename))
    path = (settings.pricebook_dir / safe).resolve()
    if not path.is_relative_to(settings.pricebook_dir.resolve()):
        raise ValueError(f"catalog file must be inside {settings.pricebook_dir}: {filename!r}")
    return path


async def read_entries(book: dict[str, Any], path: Path, vendor: str) -> str:
    """Read the book's price tables into priceBookEntries, once per file version.

    Rows are keyed to the file's SHA and never overwritten: a new sheet adds a
    version and the book points at it, so a quote priced off the old one can
    still say which file and page its number came from (NFR-3).
    """
    file_sha = catalog_store.file_hash(path)
    entries = price_book_entries()
    if await entries.find_one({"priceBookId": book["_id"], "fileSha": file_sha}, {"_id": 1}) is None:
        read = await asyncio.to_thread(pricebook_reader.read_book, path)
        now = _now()
        documents = [
            {
                "priceBookId": book["_id"],
                "fileSha": file_sha,
                "file": path.name,
                "vendor": vendor,
                "page": page.page,
                "printedPage": page.printed_page,
                "effective": page.effective or book.get("effective"),
                "section": page.title,
                "table": row.table,
                "model": row.model,
                "size": row.size,
                "finish": row.finish,
                "description": row.description,
                "listPrice": row.list_price,
                "bbox": row.bbox,
                "createdAt": now,
            }
            for page in read["pages"]
            for row in page.rows
        ]
        for start in range(0, len(documents), 1000):
            await entries.insert_many(documents[start : start + 1000], ordered=False)
        unread = read["unread_pages"]
    else:
        unread = (book.get("entries") or {}).get("unreadPages", [])
    count = await entries.count_documents({"priceBookId": book["_id"], "fileSha": file_sha})
    await price_books().update_one(
        {"_id": book["_id"]},
        {"$set": {"entries": {"fileSha": file_sha, "count": count, "unreadPages": unread, "readAt": _now()},
                  "updatedAt": _now()}},
    )
    return f"{count} list price(s) read" + (f"; {len(unread)} table page(s) not read" if unread else "")


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
        book = await price_books().find_one({"_id": oid(payload["priceBookId"])})

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

    read = ""
    if book:
        try:
            read = await read_entries(book, path, vendor)
        except Exception as exc:  # the page index above is the job; the tables are a bonus
            read = f"price tables not read: {type(exc).__name__}: {exc}"[:300]

    if document is None:
        if book:
            await price_books().update_one(
                {"_id": book["_id"]}, {"$set": {"indexStatus": "ready", "updatedAt": _now()}}
            )
        return "unchanged since the last index - its pages are already described" + (f"; {read}" if read else "")

    if book:
        await price_books().update_one(
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
        + (f"; {read}" if read else "")
    )
