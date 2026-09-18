"""The delete_catalog job: remove a price book's page index once its file is gone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.catalog.features import ParseCatalog, ParseMultiplier
from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.modules.catalog.api.pageindex import store as pageindex_store
from cbc.shared.mongo import oid


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def delete_catalog(job: dict[str, Any]) -> str:
    """Remove a catalog's index when its file is deleted.

    Nothing outlives the PDF it describes: a page description for a sheet that is
    gone would route a pricing pass at a file nobody can open. Also purges
    MinerU catalogPages / multiplierPages and artefact dirs.
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

    pages_removed = 0
    if payload.get("priceBookId"):
        pages_removed += await ParseCatalog.purge_pages(
            price_book_id=str(payload["priceBookId"])
        )
        await price_books().update_one(
            {"_id": oid(payload["priceBookId"])},
            {"$set": {"catalogId": None, "indexStatus": "removed", "updatedAt": _now()}},
        )
    sheet_id = catalog_id or (
        pageindex_store.catalog_id_for(filename) if filename else None
    )
    if sheet_id:
        if not payload.get("priceBookId"):
            pages_removed += await ParseCatalog.purge_pages(catalog_id=sheet_id)
        pages_removed += await ParseMultiplier.purge_pages(sheet_id=sheet_id)

    # Verified rather than assumed - the point of doing this on the queue.
    still_there = bool(catalog_id and await pageindex_store.get(str(catalog_id)))
    if still_there:
        raise RuntimeError(f"{catalog_id} is still in the page index after deletion")

    parts = []
    if removed:
        parts.append(f"{removed} catalog index/indexes removed")
    elif not pages_removed:
        parts.append("nothing was indexed for it")
    if pages_removed:
        parts.append(f"{pages_removed} parsed page(s) purged")
    return "; ".join(parts)
