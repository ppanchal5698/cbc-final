"""Durable cache of PDF page text and clustered table rows (audit C-02 / B-12).

`find_sheets` and `search_pdf` used to call `get_text()` on every page of every
call. The render cache already lives under `.cache/`; this is the text sibling,
keyed on file SHA + extractor version so a changed sheet or a clustering fix
cannot serve a stale payload.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from cbc.core import pdfpages, pdfrows
from cbc.core.paths import repo_root

ROOT = repo_root()
CACHE_DB = ROOT / ".cache" / "pdftext.db"

_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    handle = getattr(_local, "conn", None)
    db_path = str(CACHE_DB)
    if handle is not None and getattr(_local, "path", None) == db_path:
        return handle
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    handle = sqlite3.connect(db_path, timeout=5)
    handle.execute("PRAGMA journal_mode=WAL")
    handle.execute(
        """
        CREATE TABLE IF NOT EXISTS pdftext (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            extracted_at TEXT NOT NULL
        )
        """
    )
    handle.commit()
    _local.conn = handle
    _local.path = db_path
    return handle


def reset() -> None:
    """Drop the thread-local connection so tests can point at another file."""
    handle = getattr(_local, "conn", None)
    if handle is not None:
        handle.close()
    _local.conn = None
    _local.path = None


def cache_key(
    file_path: str | Path,
    op: str,
    page: int | None,
    options: dict[str, Any] | None = None,
) -> str:
    blob = json.dumps(
        {
            "sha": pdfpages.content_sha256(file_path),
            "extractor": pdfrows.EXTRACTOR_VERSION,
            "op": op,
            "page": page,
            "options": options or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(key: str) -> dict[str, Any] | None:
    row = _connect().execute(
        "SELECT payload FROM pdftext WHERE cache_key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def put(key: str, payload: dict[str, Any]) -> None:
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO pdftext (cache_key, payload, extracted_at) VALUES (?, ?, ?)",
        (key, json.dumps(payload, separators=(",", ":"), default=str), _now()),
    )
    conn.commit()


def shifted_page_text(
    file_path: str | Path, page_index: int, page: fitz.Page, shift: int
) -> str:
    """Shifted `get_text()` for one page, cached."""
    key = cache_key(file_path, "page_text", page_index, {"shift": shift})
    hit = get(key)
    if hit is not None:
        return str(hit.get("text") or "")
    text = pdfrows.shift_text(page.get_text(), shift)
    put(key, {"text": text})
    return text


def clustered_rows(
    file_path: str | Path,
    page_index: int,
    page: fitz.Page,
    region: list[float] | None,
    shift: int,
) -> list[dict[str, Any]]:
    """`rows_from_words` for one page, cached (always with cell_boxes)."""
    options = {
        "shift": shift,
        "region": None if not region else [float(v) for v in region[:4]],
    }
    key = cache_key(file_path, "rows", page_index, options)
    hit = get(key)
    if hit is not None:
        return list(hit.get("rows") or [])
    rows = pdfrows.rows_from_words(page, region, shift)
    put(key, {"rows": rows})
    return rows
