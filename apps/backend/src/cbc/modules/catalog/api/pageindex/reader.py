"""Reading the page index from a synchronous process, with no write access.

The MCP servers are sync and run inside the Claude Code subprocess, which
`provider.WITHHELD` deliberately denies the root connection string: pymongo is in
the image, so a single Bash call with that URI could write to any collection,
straight past every read-only assertion the tools make about themselves.

So this connects with `MONGODB_READONLY_URI` and nothing else. If that variable
is absent the reader refuses rather than reaching for the writable one - a
pricing pass that can edit the catalog is a worse outcome than a pricing pass
that cannot read it, because the first one fails silently.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

_client = None

COLLECTION = "pageIndex"


class ReadOnlyIndexUnavailable(RuntimeError):
    """No read-only credential, so there is nothing safe to connect with."""


def _collection():
    global _client
    if _client is None:
        uri = os.environ.get("MONGODB_READONLY_URI")
        if not uri:
            raise ReadOnlyIndexUnavailable(
                "MONGODB_READONLY_URI is not set. The catalog server reads the page "
                "index with a credential that cannot write; it will not fall back "
                "to the writable connection string."
            )
        from pymongo import MongoClient

        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _client[_database_name()][COLLECTION]


def _database_name() -> str:
    """Which database, taken from the connection string that was handed over.

    Not from an environment variable of its own: the URI already names the
    database, and reading the two separately means they can disagree. They did -
    the suite points settings at a test database, the URI followed, and this read
    the default, so every lookup came back empty against a populated index.
    """
    uri = os.environ.get("MONGODB_READONLY_URI", "")
    path = urlsplit(uri).path.lstrip("/").split("?")[0]
    return path or os.environ.get("MONGODB_DB") or "cbc_opshub"


def reset() -> None:
    """Drop the cached client, so a changed connection string is picked up."""
    global _client
    if _client is not None:
        _client.close()
    _client = None


def available() -> bool:
    try:
        _collection().database.client.admin.command("ping")
        return True
    except Exception:
        return False


def list_catalogs(vendor: str | None = None) -> list[dict[str, Any]]:
    query = {"vendor": vendor.strip().lower()} if vendor else {}
    return list(
        _collection().find(query, {"pages": 0, "profile": 0}).sort("vendor", 1).limit(200)
    )


def get_catalog(catalog_id: str) -> dict[str, Any] | None:
    return _collection().find_one({"_id": catalog_id})


def all_catalogs(vendor: str | None = None) -> list[dict[str, Any]]:
    """Page documents for ranking, without profile or spreadsheet row ranges."""
    query = {"vendor": vendor.strip().lower()} if vendor else {}
    projection = {
        "profile": 0,
        "pages.rows": 0,
        "pages.sheet": 0,
    }
    return list(_collection().find(query, projection).limit(50))
