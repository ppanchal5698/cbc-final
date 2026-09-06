"""Autopilot saga: maybe_continue_chain respects chainState."""
from __future__ import annotations

import asyncio
import os

import pytest
from bson import ObjectId
from pymongo import MongoClient

from cbc import db as db_module
from cbc.config import settings
from tests.shared import mongo_client

TEST_DB = "cbc_test_orchestrator_chain"


def run(coro):
    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


@pytest.fixture()
def database():
    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw.server_info()
    except Exception as exc:
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but MongoDB is not reachable: {exc}")
        pytest.skip("MongoDB is not running")
    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    raw.drop_database(TEST_DB)
    db_module._client = None
    asyncio.run(db_module.ensure_indexes())
    db_module._client = None
    try:
        yield raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def test_needs_review_does_not_enqueue_pricing(database) -> None:
    from cbc.services import orchestrator

    project_id = ObjectId()
    database["projects"].insert_one(
        {"_id": project_id, "code": "CH-1", "slug": "ch1", "chainState": "extraction_needs_review"}
    )
    job = {
        "type": "extract_bid_set",
        "projectId": project_id,
        "payload": {"orchestrate": True},
        "createdBy": "test",
    }
    assert run(orchestrator.maybe_continue_chain(job)) is None
    assert database["jobs"].count_documents({}) == 0


def test_extraction_done_enqueues_pricing(database) -> None:
    from cbc.services import orchestrator

    project_id = ObjectId()
    database["projects"].insert_one(
        {"_id": project_id, "code": "CH-2", "slug": "ch2", "chainState": "extraction_done"}
    )
    job = {
        "type": "extract_bid_set",
        "projectId": project_id,
        "payload": {"orchestrate": True},
        "createdBy": "test",
    }
    nxt = run(orchestrator.maybe_continue_chain(job))
    assert nxt is not None
    assert nxt["type"] == "match_and_price"
    stored = database["projects"].find_one({"_id": project_id})
    assert stored["chainState"] == "pricing"


def test_pricing_failure_disables_autopilot(database) -> None:
    from cbc.services import chain

    project_id = ObjectId()
    database["projects"].insert_one(
        {"_id": project_id, "code": "CH-3", "slug": "ch3", "autopilot": True, "chainState": "pricing"}
    )
    run(chain.set_state(project_id, "pricing_failed", detail="catalog down"))
    stored = database["projects"].find_one({"_id": project_id})
    assert stored["autopilot"] is False
    assert stored["chainState"] == "pricing_failed"


def test_autopilot_off_does_not_enqueue_quoting(database) -> None:
    from cbc.services import orchestrator

    project_id = ObjectId()
    database["projects"].insert_one(
        {
            "_id": project_id,
            "code": "CH-4",
            "slug": "ch4",
            "autopilot": False,
            "chainState": "pricing",
        }
    )
    job = {
        "type": "match_and_price",
        "projectId": project_id,
        "payload": {"orchestrate": True},
        "createdBy": "test",
    }
    assert run(orchestrator.maybe_continue_chain(job)) is None
    assert database["jobs"].count_documents({}) == 0
