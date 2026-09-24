"""The seeded take-off reaches the review screen while the pass is still running.

`prepare` writes a real take-off before the first token is generated - that is
the point of seeding, so the model checks rows instead of inventing them. But
the import lived only in `sync_results`, the job's *completion* hook, and the
review screen reads the `openings` collection. So for the whole run the
estimator saw an empty table under a banner promising lines would appear as they
were found. On a 24-page set that was the parse plus the entire wave.

The rows exist on disk the whole time. This pins that they reach Mongo at
`prepare`, and - the part that makes it safe - that the end-of-job import still
wins for rows the estimator has not touched and still defers to the ones they
have.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cbc.modules.extraction.api import passes


@pytest.mark.anyio
async def test_prepare_imports_the_seeded_openings(monkeypatch) -> None:
    project = {"_id": "bid-1", "slug": "bid", "code": "CBC-1"}
    job = {"type": "extract_bid_set"}

    monkeypatch.setattr(passes.sheetmap, "build_sheetmap", lambda *a, **k: None)
    monkeypatch.setattr(
        passes.pretakeoff, "seed_door_schedule",
        lambda slug: {"openings": 6, "page": 16, "preserved": 0, "note": ""},
    )
    monkeypatch.setattr(
        passes.pretakeoff, "seed_hardware_groups",
        lambda slug: {"sets": 0, "items": 0, "pages": [], "note": ""},
    )
    monkeypatch.setattr(
        passes.pretakeoff, "seed_scope_summary", lambda slug: {"written": True},
    )
    monkeypatch.setattr(
        passes.pretakeoff, "seed_scope_metadata", lambda slug, project: {"written": True},
    )
    monkeypatch.setattr(passes.visual_pages, "build_visual_pages", lambda *a, **k: {"pages": []})
    monkeypatch.setattr(passes, "_parse_signals_by_path", AsyncMock(return_value=None))
    monkeypatch.setattr(passes.sheetmap, "exceeds_page_cap", lambda *a, **k: (False, 24))

    from cbc.modules.extraction.api import line_items

    imported = AsyncMock(return_value={"inserted": 6, "updated": 0, "skipped": 0})
    monkeypatch.setattr(line_items, "import_extraction", imported)

    assert await passes.prepare(job, project, {}) is True
    imported.assert_awaited_once()
    # The lease has to be passed, or a worker whose claim was stolen writes rows
    # for a job it no longer owns.
    assert imported.await_args.kwargs.get("job") is job


@pytest.mark.anyio
async def test_a_bid_set_over_the_page_cap_imports_nothing(monkeypatch) -> None:
    """The job is already finished by then; importing would contradict it."""
    project = {"_id": "bid-1", "slug": "bid", "code": "CBC-1"}
    job = {"type": "extract_bid_set"}

    monkeypatch.setattr(passes.sheetmap, "build_sheetmap", lambda *a, **k: None)
    monkeypatch.setattr(
        passes.pretakeoff, "seed_door_schedule",
        lambda slug: {"openings": 6, "page": 16, "preserved": 0, "note": ""},
    )
    monkeypatch.setattr(
        passes.pretakeoff, "seed_hardware_groups",
        lambda slug: {"sets": 0, "items": 0, "pages": [], "note": ""},
    )
    monkeypatch.setattr(passes.pretakeoff, "seed_scope_summary", lambda slug: {"written": True})
    monkeypatch.setattr(
        passes.pretakeoff, "seed_scope_metadata", lambda slug, project: {"written": True},
    )
    monkeypatch.setattr(passes.visual_pages, "build_visual_pages", lambda *a, **k: {"pages": []})
    monkeypatch.setattr(passes, "_parse_signals_by_path", AsyncMock(return_value=None))
    monkeypatch.setattr(passes.sheetmap, "exceeds_page_cap", lambda *a, **k: (True, 900))
    monkeypatch.setattr(passes.bids, "note_phase", AsyncMock())
    monkeypatch.setattr(passes.ops_worker, "finish", AsyncMock())
    monkeypatch.setattr(passes, "EXTRACT_MAX_PDF_PAGES", 100)

    from cbc.modules.extraction.api import line_items

    imported = AsyncMock()
    monkeypatch.setattr(line_items, "import_extraction", imported)

    assert await passes.prepare(job, project, {}) is False
    imported.assert_not_awaited()
