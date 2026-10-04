"""parse_document runs its windows concurrently, bounded, and resumes.

A window is ~97% waiting on the API (measured: ~174s API vs ~4s of our code on an
87-page set), so running them one after another turned three minutes of work into
thirty-two. These tests fail if the loop goes back to sequential.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bson import ObjectId

import pytest

from cbc.modules.intake.features import ParseDocument

DOC_ID = ObjectId()
PROJ_ID = ObjectId()


class _Docs:
    """Minimal documents collection: one document, updates recorded."""

    def __init__(self, doc: dict, sets: list):
        self._doc = doc
        self._sets = sets

    async def find_one(self, *_a, **_k):
        return self._doc

    async def update_one(self, _filter, update, **_k):
        self._sets.append(update.get("$set", {}))


class _Pages:
    def __init__(self, existing: int = 0):
        self.existing = existing
        self.upserts: list[int] = []

    async def count_documents(self, _filter):
        return self.existing

    async def update_one(self, filt, _update, **_k):
        self.upserts.append(filt["page"])


def _window_payload(start: int, end: int) -> list[dict]:
    return [
        {"page": p, "width": 612.0, "height": 792.0, "items": []}
        for p in range(start, end + 1)
    ]


def _run_job(*, pages: int, window: int, concurrency: int, parse_window, existing=0):
    doc = {
        "_id": DOC_ID,
        "projectId": PROJ_ID,
        "path": "uploads/raw/x.pdf",
        "pages": pages,
        "contentSha": "sha",
        "filename": "x.pdf",
        "parse": {"fileId": "file-1"},
    }
    sets: list[dict] = []
    pages_col = _Pages(existing)

    resolved = {
        "apiKey": "llx-k",
        "tier": "cost_effective",
        "windowPages": window,
        "windowConcurrency": concurrency,
        "windowTimeoutSeconds": 60,
        "lang": "en",
    }

    async def go():
        with (
            patch.object(ParseDocument, "_load_settings", AsyncMock(return_value=resolved)),
            patch.object(ParseDocument, "documents", lambda: _Docs(doc, sets)),
            patch.object(ParseDocument, "document_pages", lambda: pages_col),
            patch.object(ParseDocument, "_project_slug", AsyncMock(return_value="slug")),
            patch.object(ParseDocument.storage, "absolute", lambda _p: Path(__file__)),
            patch.object(ParseDocument.storage, "project_dir") as pdir,
            patch.object(ParseDocument.worker, "job_cancelled", AsyncMock(return_value=False)),
            patch.object(ParseDocument.llamaparse, "upload", AsyncMock(return_value="file-1")),
            patch.object(ParseDocument.llamaparse, "parse_window", parse_window),
            patch.object(
                ParseDocument.page_blocks,
                "normalise_window",
                lambda payload, **_k: [
                    {"page": p["page"], "blocks": [], "verified": None} for p in payload
                ],
            ),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                pdir.return_value = Path(tmp)
                return await ParseDocument.parse_document({"_id": "job1", "payload": {"documentId": str(DOC_ID)}})

    return asyncio.run(go()), sets, pages_col


@pytest.mark.asyncio
async def test_windows_overlap_instead_of_queueing_behind_each_other():
    """The whole point: wall clock is the slowest window, not their sum."""
    inflight = 0
    peak = 0

    async def parse_window(_client, *, start_page, end_page, **_k):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        try:
            await asyncio.sleep(0.05)  # stands in for ~174s of API wait
            return _window_payload(start_page, end_page)
        finally:
            inflight -= 1

    note, _sets, pages_col = await asyncio.to_thread(
        lambda: _run_job(pages=32, window=8, concurrency=4, parse_window=parse_window)
    )

    # Assert the mechanism, not the clock: 32 pages at 8 per window is 4 windows,
    # and with a limit of 4 all of them should be in flight together. A wall-clock
    # assertion here measured fixture setup as much as the parse and was flaky.
    assert peak == 4, f"expected all 4 windows in flight, saw at most {peak}"
    assert sorted(pages_col.upserts) == list(range(1, 33))
    assert "4 at a time" in note


@pytest.mark.asyncio
async def test_concurrency_is_bounded_by_the_setting():
    inflight = 0
    peak = 0

    async def parse_window(_client, *, start_page, end_page, **_k):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        try:
            await asyncio.sleep(0.02)
            return _window_payload(start_page, end_page)
        finally:
            inflight -= 1

    await asyncio.to_thread(
        lambda: _run_job(pages=80, window=8, concurrency=2, parse_window=parse_window)
    )
    assert peak <= 2, f"{peak} windows in flight with windowConcurrency=2"


@pytest.mark.asyncio
async def test_progress_counts_stored_pages_not_the_last_end_page():
    """Out-of-order completion must not let a late window claim earlier pages."""

    async def parse_window(_client, *, start_page, end_page, **_k):
        # Later windows finish first, which is exactly what unordered means.
        await asyncio.sleep(0.05 if start_page == 1 else 0.01)
        return _window_payload(start_page, end_page)

    _note, sets, _pages = await asyncio.to_thread(
        lambda: _run_job(pages=24, window=8, concurrency=3, parse_window=parse_window)
    )
    progress = [s["parse.pagesDone"] for s in sets if "parse.pagesDone" in s]
    assert progress, "no progress was reported"
    assert progress == sorted(progress), f"pagesDone went backwards: {progress}"
    assert progress[-1] == 24
    assert max(progress) <= 24


@pytest.mark.asyncio
async def test_already_parsed_windows_are_skipped_on_resume():
    """A resumed job must not re-pay for windows already stored."""
    called: list[tuple[int, int]] = []

    async def parse_window(_client, *, start_page, end_page, **_k):
        called.append((start_page, end_page))
        return _window_payload(start_page, end_page)

    # count_documents returns a full window every time, so every window is skipped.
    _note, sets, _pages = await asyncio.to_thread(
        lambda: _run_job(pages=16, window=8, concurrency=2, parse_window=parse_window, existing=8)
    )
    assert called == [], "a stored window was parsed again"
    progress = [s["parse.pagesDone"] for s in sets if "parse.pagesDone" in s]
    assert progress[-1] == 16, "skipped windows must still count as done"
