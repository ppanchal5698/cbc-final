"""The repository cannot forget the tenant, the envelope, or a soft delete.

§4.1 requires that the data-access layer inject `orgId` into every query. These
tests are that requirement, written down: if a read or a write can escape the
scope without going through `.collection`, one of them fails.
"""
from __future__ import annotations

import asyncio

import pytest

from cbc.persistence import envelope, names
from cbc.persistence.repository import Repository
from tests.shared import mongo_client

TEST_DB = "cbc_opshub_test_repository"
ORG = "org-cbc"
OTHER = "org-someone-else"


@pytest.fixture()
def repo():
    from cbc import db as db_module
    from cbc.config import settings

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")

    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    db_module._client = None
    raw.drop_database(TEST_DB)
    try:
        yield lambda collection=names.OPENINGS, actor="user1": Repository(
            db_module.database()[collection], org_id=ORG, actor_id=actor
        ), raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def run(coro):
    from cbc import db as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


# ── the tenant filter ───────────────────────────────────────────────────────


def test_an_insert_carries_the_envelope(repo) -> None:
    make, raw = repo
    run(make().insert({"mark": "01"}))

    row = raw[names.OPENINGS].find_one({})
    assert row["orgId"] == ORG
    assert row["schemaVersion"] == envelope.SCHEMA_VERSION
    assert row["createdBy"] == row["updatedBy"] == "user1"
    assert row["createdAt"] == row["updatedAt"]


def test_a_read_never_crosses_tenants(repo) -> None:
    make, raw = repo
    raw[names.OPENINGS].insert_one({"mark": "99", "orgId": OTHER})
    run(make().insert({"mark": "01"}))

    assert run(make().count()) == 1
    assert run(make().find_one({"mark": "99"})) is None


def test_an_update_cannot_reach_another_tenants_row(repo) -> None:
    make, raw = repo
    raw[names.OPENINGS].insert_one({"mark": "99", "orgId": OTHER, "size": "3070"})

    result = run(make().update({"mark": "99"}, {"size": "hacked"}))
    assert result.matched_count == 0
    assert raw[names.OPENINGS].find_one({"mark": "99"})["size"] == "3070"


def test_a_delete_cannot_reach_another_tenants_row(repo) -> None:
    make, raw = repo
    raw[names.OPENINGS].insert_one({"mark": "99", "orgId": OTHER})

    run(make().delete({"mark": "99"}))
    assert raw[names.OPENINGS].count_documents({"mark": "99"}) == 1


# ── the envelope on updates ─────────────────────────────────────────────────


def test_an_update_stamps_the_actor_without_touching_created_at(repo) -> None:
    make, raw = repo
    run(make().insert({"mark": "01"}))
    created = raw[names.OPENINGS].find_one({})

    run(make(actor="user2").update({"mark": "01"}, {"size": "3070"}))
    after = raw[names.OPENINGS].find_one({})

    assert after["size"] == "3070"
    assert after["updatedBy"] == "user2"
    assert after["createdBy"] == "user1", "an edit rewrote who created the row"
    assert after["createdAt"] == created["createdAt"]


def test_a_raw_operator_keeps_its_envelope(repo) -> None:
    """An `$inc` must not lose `updatedAt` just because it brought no `$set`."""
    make, raw = repo
    run(make().insert({"mark": "01", "attempts": 0}))

    run(make().apply({"mark": "01"}, {"$inc": {"attempts": 1}}))
    row = raw[names.OPENINGS].find_one({})

    assert row["attempts"] == 1
    assert row["updatedBy"] == "user1"
    assert row["updatedAt"] >= row["createdAt"]


# ── §4.3 soft delete ────────────────────────────────────────────────────────


def test_a_soft_deleted_collection_marks_rather_than_removes(repo) -> None:
    make, raw = repo

    async def go():
        bids = make(names.BID_REQUESTS)
        assert bids.soft_deleted
        await bids.insert({"code": "CBC-260002"})
        await bids.delete({"code": "CBC-260002"})
        return await bids.count()

    visible = run(go())

    stored = raw[names.BID_REQUESTS].find_one({})
    assert stored is not None, "a soft delete removed the document"
    assert stored["isDeleted"] is True
    assert stored["deletedBy"] == "user1"
    assert visible == 0, "a deleted bid is still visible to reads"


def test_a_hard_deleted_collection_really_removes(repo) -> None:
    make, raw = repo

    async def go():
        openings = make(names.OPENINGS)
        assert not openings.soft_deleted
        await openings.insert({"mark": "01"})
        await openings.delete({"mark": "01"})

    run(go())
    assert raw[names.OPENINGS].count_documents({}) == 0


def test_a_deleted_row_can_still_be_audited(repo) -> None:
    """§4.3: unless explicitly restoring or auditing."""
    make, raw = repo

    async def go():
        bids = make(names.BID_REQUESTS)
        await bids.insert({"code": "CBC-260002"})
        await bids.delete({"code": "CBC-260002"})
        return await bids.collection.find_one(bids.scope({}, deleted=True))

    assert run(go())["code"] == "CBC-260002"


def test_pre_backfill_documents_are_not_hidden(repo) -> None:
    """`isDeleted: False` would make every document written before §4.3 vanish."""
    make, raw = repo
    raw[names.BID_REQUESTS].insert_one({"code": "OLD", "orgId": ORG})
    assert run(make(names.BID_REQUESTS).count()) == 1


# ── the escape hatch ────────────────────────────────────────────────────────


def test_the_raw_collection_is_reachable_and_scope_is_reusable(repo) -> None:
    """An aggregate still gets the guarantees, if it asks for them."""
    make, raw = repo
    raw[names.OPENINGS].insert_one({"mark": "99", "orgId": OTHER})

    async def go():
        openings = make()
        await openings.insert({"mark": "01"})
        return await openings.collection.count_documents(openings.scope({}))

    assert run(go()) == 1
