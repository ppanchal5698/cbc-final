"""Live freshness bands for catalogs, price books, and P21 last-PO dates.

Defaults live in `cbc.core.freshness`. Admins override them from Settings; the
document is `settings` `_id: "freshness"`. Callers resolve at use time so a
saved change is visible without restarting the API or an MCP process.

The sync loader reads with `MONGODB_READONLY_URI` only. Catalog and P21 MCP
servers must not fall back to the writable string.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cbc.core import freshness as core

DOC_ID = "freshness"
_TTL_SECONDS = 30.0

_cache: tuple[float, "Bands"] | None = None
_sync_client = None


@dataclass(frozen=True)
class Bands:
    catalog_stale_months: int
    discard_after_months: int
    catalog_stale_days: int
    discard_after_days: int
    rule: str
    updated_at: Any = None
    updated_by: str | None = None

    @property
    def fresh_days(self) -> int:
        return self.catalog_stale_days

    @property
    def fresh_months(self) -> int:
        return self.catalog_stale_months


DEFAULTS = Bands(
    catalog_stale_months=core.FRESH_MONTHS,
    discard_after_months=core.DISCARD_AFTER_MONTHS,
    catalog_stale_days=core.FRESH_DAYS,
    discard_after_days=core.DISCARD_AFTER_DAYS,
    rule=core.RULE,
)


def clear_cache() -> None:
    global _cache
    _cache = None


def from_document(doc: dict[str, Any] | None) -> Bands:
    """Accept a stored settings row, or fall back to the kernel defaults."""
    if not doc:
        return DEFAULTS
    try:
        catalog_months = int(doc["catalogStaleMonths"])
        discard_months = int(doc["discardAfterMonths"])
    except (KeyError, TypeError, ValueError):
        return DEFAULTS
    if not (1 <= catalog_months < discard_months <= core.MAX_MONTHS):
        return DEFAULTS
    return Bands(
        catalog_stale_months=catalog_months,
        discard_after_months=discard_months,
        catalog_stale_days=core.days_from_months(catalog_months),
        discard_after_days=core.days_from_months(discard_months),
        rule=core.rule_text(catalog_months, discard_months),
        updated_at=doc.get("updatedAt"),
        updated_by=doc.get("updatedBy"),
    )


def _remember(bands: Bands) -> Bands:
    global _cache
    _cache = (time.monotonic(), bands)
    return bands


def _cached() -> Bands | None:
    if _cache is None:
        return None
    stamped, bands = _cache
    if time.monotonic() - stamped > _TTL_SECONDS:
        return None
    return bands


async def load() -> Bands:
    """API path: the application Mongo handle, which can write settings too."""
    hit = _cached()
    if hit is not None:
        return hit
    from cbc.db import db

    try:
        doc = await db.settings.find_one({"_id": DOC_ID})
    except Exception:
        return _remember(DEFAULTS)
    return _remember(from_document(doc))


def load_sync() -> Bands:
    """MCP / script path: read-only URI or defaults. Never the writable string."""
    hit = _cached()
    if hit is not None:
        return hit
    collection = _settings_collection()
    if collection is None:
        return _remember(DEFAULTS)
    try:
        doc = collection.find_one({"_id": DOC_ID})
    except Exception:
        return _remember(DEFAULTS)
    return _remember(from_document(doc))


def as_payload(bands: Bands) -> dict[str, Any]:
    return {
        "catalogStaleMonths": bands.catalog_stale_months,
        "discardAfterMonths": bands.discard_after_months,
        "catalogStaleDays": bands.catalog_stale_days,
        "discardAfterDays": bands.discard_after_days,
        "rule": bands.rule,
        "note": (
            "Price books and vendor catalogs are stale after the review window. "
            "P21 last-PO costs are fresh for the same window, unreliable until "
            "the discard band, and discarded after that. Nothing is guessed."
        ),
        "updatedAt": bands.updated_at,
        "updatedBy": bands.updated_by,
    }


def _settings_collection():
    """The settings collection, or None when there is no read-only credential."""
    global _sync_client
    uri = os.environ.get("MONGODB_READONLY_URI")
    if not uri:
        return None
    if _sync_client is None:
        from pymongo import MongoClient

        _sync_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    path = urlsplit(uri).path.lstrip("/").split("?")[0]
    database = path or os.environ.get("MONGODB_DB") or "cbc_opshub"
    return _sync_client[database]["settings"]


def reset_sync_client() -> None:
    """Drop the cached pymongo client so a changed URI is picked up."""
    global _sync_client
    if _sync_client is not None:
        _sync_client.close()
    _sync_client = None
    clear_cache()
