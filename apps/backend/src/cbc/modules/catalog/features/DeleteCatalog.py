"""The delete_catalog job: remove a price book's page index once its file is gone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.catalog.infrastructure.collections import price_books
from cbc.modules.catalog.api.pageindex import store as pageindex_store
from cbc.shared.mongo import oid


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        await price_books().update_one(
            {"_id": oid(payload["priceBookId"])},
            {"$set": {"catalogId": None, "indexStatus": "removed", "updatedAt": _now()}},
        )

    # Verified rather than assumed - the point of doing this on the queue.
    still_there = bool(catalog_id and await pageindex_store.get(str(catalog_id)))
    if still_there:
        raise RuntimeError(f"{catalog_id} is still in the page index after deletion")

    return f"{removed} catalog index/indexes removed" if removed else "nothing was indexed for it"
