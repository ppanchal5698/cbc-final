"""Where a page index lives: one MongoDB document per catalog.

The write side runs in the worker, which is the only writer. The read side is
used by the API and, through a read-only credential, by the catalog MCP server -
`provider.WITHHELD` denies the Claude subprocess the root connection string on
purpose, and `cbc.db.readonly_uri()` is what exists for exactly this.

Deleting a catalog deletes its index. Nothing here outlives the PDF it describes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from cbc.db import database
from cbc.pageindex.models import PageIndexDocument

COLLECTION = "pageIndex"


def file_hash(path: Path) -> str:
    """Content hash, so an unchanged file is never re-read or re-described."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def catalog_id_for(file_name: str) -> str:
    """Stable id from the file name, so a re-upload updates rather than duplicates."""
    return Path(file_name).stem.lower().replace(" ", "_")


def _collection():
    return database()[COLLECTION]


async def ensure_indexes() -> None:
    collection = _collection()
    await collection.create_index("vendor")
    await collection.create_index("fileName")
    # What `find_pages` searches: the title and description of every page, plus
    # the catalog summary. One text index, because the question is always the
    # same one - which page do I open.
    await collection.create_index(
        [
            ("pages.title", "text"),
            ("pages.description", "text"),
            ("overview.summary", "text"),
        ],
        name="page_text",
    )


async def save(document: PageIndexDocument) -> None:
    """Upsert one catalog's index. Idempotent on catalog_id."""
    payload = document.to_mongo()
    await _collection().replace_one({"_id": payload["_id"]}, payload, upsert=True)


async def get(catalog_id: str) -> PageIndexDocument | None:
    row = await _collection().find_one({"_id": catalog_id})
    return PageIndexDocument.from_mongo(row) if row else None


async def get_by_file(file_name: str) -> PageIndexDocument | None:
    row = await _collection().find_one({"fileName": file_name})
    return PageIndexDocument.from_mongo(row) if row else None


async def stored_hash(catalog_id: str) -> str | None:
    """The hash of what is already indexed, for deciding whether to rebuild."""
    row = await _collection().find_one({"_id": catalog_id}, {"fileHash": 1})
    return (row or {}).get("fileHash")


async def list_catalogs(vendor: str | None = None) -> list[dict[str, Any]]:
    """Catalog headers without the page arrays - a listing, not a download."""
    query = {"vendor": vendor.strip().lower()} if vendor else {}
    projection = {"pages": 0, "profile": 0}
    rows = await _collection().find(query, projection).sort("vendor", 1).to_list(200)
    return rows


async def delete(catalog_id: str) -> bool:
    """Drop one catalog's index. Called when its PDF is deleted."""
    result = await _collection().delete_one({"_id": catalog_id})
    return result.deleted_count > 0


async def delete_by_file(file_name: str) -> int:
    result = await _collection().delete_many({"fileName": file_name})
    return result.deleted_count
