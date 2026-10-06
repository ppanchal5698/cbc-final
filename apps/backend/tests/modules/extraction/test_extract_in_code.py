"""extract_bid_set in code (v2): a bid set read by the parsers and landed in
`openings` - against a throwaway Mongo, no model and no Claude pass."""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest
from bson import ObjectId

from cbc.shared.config import settings
from cbc.shared.persistence import names
from tests.shared import FIXTURES, mongo_client

TEST_DB = "cbc_test_extract_in_code"
SLUG = "extract_in_code_fixture"

ROWS = [
    ["DOOR NO.", "WIDTH", "HEIGHT", "FIRE RATING", "HARDWARE GROUP"],
    ["101", "3'-0\"", "7'-0\"", "90 MIN", "GROUP 1"],
    ["102", "3'-0\"", "7'-0\"", "20 MIN", "GROUP 1"],
    ["A12", "3'-6\"", "7'-0\"", "NONE", "GROUP 2"],
]


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


def _schedule_sheet(path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_text((72, 60), "DOOR SCHEDULE", fontsize=14)
    for row, cells in enumerate(ROWS):
        for column, text in enumerate(cells):
            page.insert_text((72 + column * 150, 120 + row * 24), text, fontsize=9)
    doc.save(path)
    doc.close()


async def _true(*_args, **_kwargs) -> bool:
    return True


@pytest.fixture()
def bid(monkeypatch):
    from cbc.modules.extraction.features import ExtractBidSet
    from cbc.shared import mongo as db_module

    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw.server_info()
    except Exception as exc:
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but MongoDB is not reachable: {exc}")
        pytest.skip("MongoDB is not running")
    previous_db, settings.mongodb_db = settings.mongodb_db, TEST_DB
    previous_root = settings.storage_root
    scratch = FIXTURES / "scratch" / TEST_DB
    shutil.rmtree(scratch, ignore_errors=True)
    settings.storage_root = scratch
    monkeypatch.setenv("STORAGE_ROOT", str(scratch))  # the sheet map's lookup (cbc.shared.paths)
    raw.drop_database(TEST_DB)
    db_module._client = None

    uploads = scratch / SLUG / "uploads" / "raw"
    uploads.mkdir(parents=True)
    _schedule_sheet(uploads / "A601.pdf")
    project = {"_id": ObjectId(), "slug": SLUG, "code": "EX-001", "name": "Extract fixture"}
    raw[TEST_DB][names.BID_REQUESTS].insert_one(dict(project))
    monkeypatch.setattr(ExtractBidSet.ops_jobs, "holds_lease", _true)
    # Intake binds the documents port when the worker registers its jobs.
    monkeypatch.setattr(ExtractBidSet.documents, "mark_received", _true)
    try:
        yield project, raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db, settings.storage_root = previous_db, previous_root
        shutil.rmtree(scratch, ignore_errors=True)
        db_module._client = None


def _job(project: dict, kind: str = "extract_bid_set") -> dict:
    return {"_id": ObjectId(), "type": kind, "projectId": project["_id"], "payload": {}}


def test_a_bid_set_is_read_in_code_and_lands_without_a_pass(bid) -> None:
    from cbc.modules.extraction.api import passes
    from cbc.modules.extraction.features import ExtractBidSet

    project, db = bid
    job = _job(project)

    assert run(passes.prepare(job, project, job["payload"])) is True
    note = run(ExtractBidSet.extract_in_code(job, project))

    doors = {d["mark"]: d for d in db[names.OPENINGS].find({"projectId": project["_id"]})}
    assert sorted(doors) == ["101", "102", "A12"], note
    assert doors["101"]["hwSet"] and doors["101"]["fireRating"]
    # Every row says where it was read: the page, and the row on it.
    for door in doors.values():
        assert door["evidence"]["sourcePage"] == 1 and door["evidence"]["bbox"], door["evidence"]
    stored = db[names.BID_REQUESTS].find_one({"_id": project["_id"]})
    assert stored["stage"] == "extraction"


def test_the_extract_job_runs_in_code_when_the_switch_says_so(monkeypatch) -> None:
    """v2 runs the take-off as the job's own work - no wave, no Claude pass."""
    from cbc.modules.extraction.features import ExtractBidSet

    seen: dict = {}

    async def run_pass(job, **kwargs):
        seen.update(kwargs)

    async def engine() -> str:
        return "v2"

    monkeypatch.setattr(ExtractBidSet.ops_pipeline, "extraction_engine", engine)
    monkeypatch.setattr(ExtractBidSet.pipeline, "run_pass", run_pass)
    asyncio.run(ExtractBidSet.run({"_id": ObjectId(), "type": "extract_bid_set"}))

    assert seen["work"] is ExtractBidSet.extract_in_code
    assert "wave_for" not in seen
