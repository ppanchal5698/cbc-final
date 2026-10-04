"""The delete_catalog job: remove a price book's page index once its file is gone.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.modules.catalog.infrastructure.collections import (
    catalog_pages,
    multiplier_pages,
    price_books,
)
from cbc.modules.catalog.api.pageindex import store as pageindex_store
from cbc.shared.config import settings
from cbc.shared.mongo import oid


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Legacy artefact directories. `parse_catalog` / `parse_multiplier` went with
# the parser swap, but rows and files written before that are still on disk, and
# being deleted must still take its pages with it - a page description outliving
# the PDF it describes would route a pricing pass at a file nobody can open.
def _catalog_artefacts(price_book_id: Any) -> Path:
    return settings.pricebook_dir / "processed" / "mineru" / str(price_book_id)


def _multiplier_artefacts(sheet_id: str) -> Path:
    return settings.pricebook_dir / "processed" / "mineru" / "multipliers" / str(sheet_id)


async def _purge_catalog_pages(
    *, price_book_id: str | None = None, catalog_id: str | None = None
) -> int:
    filt: dict[str, Any] = {}
    if price_book_id:
        filt["priceBookId"] = oid(price_book_id)
    elif catalog_id:
        filt["catalogId"] = catalog_id
    else:
        return 0
    result = await catalog_pages().delete_many(filt)
    if price_book_id:
        out = _catalog_artefacts(price_book_id)
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)
    return int(result.deleted_count)


async def _purge_multiplier_pages(*, sheet_id: str | None = None) -> int:
    if not sheet_id:
        return 0
    result = await multiplier_pages().delete_many({"sheetId": sheet_id})
    out = _multiplier_artefacts(sheet_id)
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    return int(result.deleted_count)


async def delete_catalog(job: dict[str, Any]) -> str:
    """Remove a catalog's index when its file is deleted.

    Nothing outlives the PDF it describes: a page description for a sheet that is
    gone would route a pricing pass at a file nobody can open. Also purges
    legacy catalogPages / multiplierPages and their artefact dirs.
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
        pages_removed += await _purge_catalog_pages(
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
            pages_removed += await _purge_catalog_pages(catalog_id=sheet_id)
        pages_removed += await _purge_multiplier_pages(sheet_id=sheet_id)

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
