"""Coalesce ceiling, straggler flag, and capped nextAttemptAt."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from cbc.persistence import names


def run(coro):
    from cbc import db as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


@pytest.fixture()
def database(monkeypatch):
    """Isolated MongoDB database for job-queue tests."""
    import os

    from pymongo import MongoClient

    from cbc import db as db_module
    from cbc.config import settings
    from tests.shared import mongo_client

    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw.server_info()
    except Exception as exc:
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but MongoDB is not reachable: {exc}")
        pytest.skip("MongoDB is not running")

    name = "cbc_test_coalesce"
    previous = settings.mongodb_db
    settings.mongodb_db = name
    raw.drop_database(name)
    db_module._client = None
    run(db_module.ensure_indexes())

    try:
        yield raw[name]
    finally:
        raw.drop_database(name)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def test_capped_next_attempt_never_past_ceiling():
    from cbc.services.jobs import capped_next_attempt

    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    ceiling = now + timedelta(minutes=5)
    # 60s quiet window is fine.
    assert capped_next_attempt(60, ceiling, now=now) == now + timedelta(seconds=60)
    # A huge quiet window still stops at the ceiling.
    assert capped_next_attempt(600, ceiling, now=now) == ceiling


def test_repeated_uploads_do_not_starve_past_ceiling(database) -> None:
    """Each sibling may push nextAttemptAt, but never past coalesceUntil."""
    from cbc.services import jobs

    project_id = ObjectId()
    first = run(jobs.enqueue("extract_bid_set", project_id, delay_seconds=60))
    assert first.get("coalesceUntil")
    ceiling = first["coalesceUntil"]

    # Simulate many uploads that would otherwise push forever.
    last = first
    for _ in range(8):
        last = run(jobs.enqueue("extract_bid_set", project_id, delay_seconds=60))
        assert last["_id"] == first["_id"]
        assert last["nextAttemptAt"] <= ceiling

    assert last["nextAttemptAt"] == ceiling or last["nextAttemptAt"] <= ceiling


def test_upload_while_running_marks_straggler(database) -> None:
    from cbc.services import jobs

    project_id = ObjectId()
    job = run(jobs.enqueue("extract_bid_set", project_id, delay_seconds=0))
    database["jobs"].update_one(
        {"_id": job["_id"]},
        {"$set": {"status": "running", "startedAt": datetime.now(timezone.utc)}},
    )

    again = run(jobs.enqueue("extract_bid_set", project_id, delay_seconds=60))
    assert again["_id"] == job["_id"]
    assert again.get("stragglerPending") is True


def test_straggler_reextract_sets_merge_flag(database) -> None:
    from cbc.worker_kit import runtime

    project_id = ObjectId()
    job = {
        "_id": ObjectId(),
        "type": "extract_bid_set",
        "projectId": project_id,
        "status": "done",
        "stragglerPending": True,
        "payload": {"orchestrate": True},
        "createdBy": "tester",
        "startedAt": datetime.now(timezone.utc),
    }
    database["jobs"].insert_one(job)
    database[names.BID_REQUESTS].insert_one({"_id": project_id, "code": "CBC-TEST", "slug": "x"})

    follow = run(runtime._queue_straggler_reextract(job))
    assert follow is not None
    assert follow.get("payload", {}).get("stragglerMerge") is True
    assert follow["type"] == "extract_bid_set"
    stored = database[names.BID_REQUESTS].find_one({"_id": project_id})
    assert "merge" in (stored.get("pipelineNote") or "").lower()


def test_extract_prompt_includes_straggler_merge_block() -> None:
    from cbc.worker_kit import prompts

    text = prompts.build(
        {"type": "extract_bid_set", "payload": {"stragglerMerge": True}},
        {"slug": "demo", "code": "CBC-1", "name": "Demo"},
    )
    assert "STRAGGLER MERGE MODE" in text
    assert "frp_in_scope = prior OR" in text

    clean = prompts.build(
        {"type": "extract_bid_set", "payload": {}},
        {"slug": "demo", "code": "CBC-1", "name": "Demo"},
    )
    assert "STRAGGLER MERGE MODE" not in clean


def test_waiting_for_siblings_helper():
    from cbc.services.jobs import waiting_for_siblings

    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    assert waiting_for_siblings({"status": "queued", "nextAttemptAt": future}) is True
    assert waiting_for_siblings({"status": "queued", "nextAttemptAt": None}) is False
    assert waiting_for_siblings({"status": "running", "nextAttemptAt": future}) is False


def test_coalesce_note_states_debounce_ceiling():
    from cbc.services import jobs

    future = datetime.now(timezone.utc) + timedelta(seconds=45)
    ceiling = datetime.now(timezone.utc) + timedelta(seconds=300)
    note = jobs.coalesce_note(
        {
            "status": "queued",
            "nextAttemptAt": future,
            "coalesceUntil": ceiling,
        }
    )
    assert note is not None
    assert "60" in note or str(jobs.DEFAULT_COALESCE_SECONDS) in note
    assert str(jobs.COALESCE_MAX_SECONDS) in note or "hard cap" in note
