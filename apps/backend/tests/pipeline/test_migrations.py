"""The migration runner: ordered, recorded, idempotent, forward-only.

There was no migration mechanism at all before this. Index setup is idempotent
and re-runnable, so it was never the problem; changing the *shape* of stored data
was, and the repo's answer was a hand-run script - one of which `db.py` still
tells an operator to run at runtime, and which does not exist.

Every API container runs startup, so the runner has to tolerate being invoked
several times at once and after a crash. These tests hold that line.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from cbc.persistence import migrations
from tests.shared import mongo_client

TEST_DB = "cbc_opshub_test_migrations"


def _fake(name: str, version: int, description: str, body):
    """Register a throwaway migration module under this package."""
    module = types.ModuleType(f"{migrations.__name__}.{name}")
    module.VERSION = version
    module.DESCRIPTION = description
    module.apply = body
    sys.modules[module.__name__] = module
    return module


@pytest.fixture()
def database():
    """A throwaway database. The runner is async, so it gets the motor handle;
    the tests assert with pymongo, which is easier to read."""
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")

    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    db_module._client = None
    raw.drop_database(TEST_DB)
    try:
        yield raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def _pending() -> list:
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(migrations.pending(db_module.database()))
    finally:
        db_module._client = None


def _run() -> list:
    """Apply pending migrations against the database settings currently name."""
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(migrations.run(db_module.database()))
    finally:
        db_module._client = None


@pytest.fixture()
def three(monkeypatch):
    """Three migrations, deliberately declared out of order."""
    ran: list[int] = []

    def make(version):
        async def apply(db):
            ran.append(version)
            await db["evidence"].insert_one({"version": version})

        return apply

    catalogue = [
        migrations.Migration(3, "third", make(3), "m3"),
        migrations.Migration(1, "first", make(1), "m1"),
        migrations.Migration(2, "second", make(2), "m2"),
    ]
    monkeypatch.setattr(
        migrations, "discover", lambda: sorted(catalogue, key=lambda m: m.version)
    )
    return ran


# ── discovery ───────────────────────────────────────────────────────────────


def test_a_migration_missing_a_required_name_is_refused(monkeypatch) -> None:
    """A half-written migration must fail loudly, not be skipped silently."""
    broken = _fake("broken_probe", 99, "no apply", None)
    del broken.apply
    monkeypatch.setattr(
        migrations.pkgutil, "iter_modules",
        lambda path: [types.SimpleNamespace(name="broken_probe")],
    )
    monkeypatch.setattr(
        migrations.importlib, "import_module", lambda name: broken
    )
    with pytest.raises(AttributeError, match="apply"):
        migrations.discover()


def test_two_migrations_cannot_claim_one_version(monkeypatch) -> None:
    async def apply(db):
        return None

    first = _fake("dupe_a", 7, "a", apply)
    second = _fake("dupe_b", 7, "b", apply)
    modules = {"dupe_a": first, "dupe_b": second}
    monkeypatch.setattr(
        migrations.pkgutil, "iter_modules",
        lambda path: [types.SimpleNamespace(name=n) for n in modules],
    )
    monkeypatch.setattr(
        migrations.importlib, "import_module",
        lambda name: modules[name.rsplit(".", 1)[-1]],
    )
    with pytest.raises(ValueError, match="version 7"):
        migrations.discover()


def test_the_real_package_discovers_cleanly() -> None:
    """Whatever ships must satisfy the contract."""
    found = migrations.discover()
    assert [m.version for m in found] == sorted(m.version for m in found)
    assert len({m.version for m in found}) == len(found)


# ── running ─────────────────────────────────────────────────────────────────


def test_migrations_run_in_version_order(database, three) -> None:
    _run()
    assert three == [1, 2, 3], "declared 3,1,2 - must run 1,2,3"


def test_running_twice_applies_nothing_the_second_time(database, three) -> None:
    """Every API container runs startup. The second one must be a no-op."""
    _run()
    again = _run()
    assert again == []
    assert three == [1, 2, 3]
    assert database["evidence"].count_documents({}) == 3


def test_the_ledger_records_what_ran(database, three) -> None:
    _run()
    rows = list(database[migrations.LEDGER].find().sort("_id", 1))
    assert [row["_id"] for row in rows] == [1, 2, 3]
    assert rows[0]["description"] == "first"
    assert rows[0]["appliedAt"] is not None


def test_a_failing_migration_is_not_recorded_and_is_retried(database, monkeypatch) -> None:
    """The reason apply() must be idempotent rather than merely correct once."""
    attempts: list[int] = []

    async def flaky(db):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient")
        await db["evidence"].insert_one({"ok": True})

    monkeypatch.setattr(
        migrations, "discover", lambda: [migrations.Migration(1, "flaky", flaky, "m1")]
    )
    with pytest.raises(RuntimeError, match="transient"):
        _run()
    assert database[migrations.LEDGER].count_documents({}) == 0, "a failure was recorded as done"

    _run()
    assert database[migrations.LEDGER].count_documents({}) == 1
    assert database["evidence"].count_documents({}) == 1


def test_pending_reports_only_what_has_not_run(database, three) -> None:
    assert [m.version for m in _pending()] == [1, 2, 3]
    _run()
    assert _pending() == []


def test_there_is_no_way_to_migrate_backwards() -> None:
    """Forward-only is a decision, not an omission - see the package docstring."""
    assert not hasattr(migrations, "rollback")
    assert not any(hasattr(m.apply, "down") for m in migrations.discover())


# ── m001: the specification rename ──────────────────────────────────────────


def test_m001_renames_the_operational_collections(database) -> None:
    """Data survives, under the name the specification uses."""
    from cbc.persistence.names import RENAMED_IN_M001

    for old in RENAMED_IN_M001:
        database[old].insert_one({"marker": old})

    _run()

    for old, new in RENAMED_IN_M001.items():
        assert old not in database.list_collection_names(), f"{old} still exists"
        assert database[new].find_one({"marker": old}), f"{new} lost its row"


def test_m001_carries_indexes_across(database) -> None:
    """renameCollection is metadata, not a copy - the indexes come too."""
    database["lineItems"].create_index([("projectId", 1), ("mark", 1)], name="probe")
    _run()
    assert "probe" in database["openings"].index_information()


def test_m001_is_a_no_op_on_a_fresh_database(database) -> None:
    _run()
    assert database[migrations.LEDGER].count_documents({"_id": 1}) == 1
    ran_again = _run()
    assert ran_again == []


def test_m001_refuses_to_rename_over_an_existing_collection(database) -> None:
    """Both names present means a half-migrated database - a question for a person."""
    database["projects"].insert_one({"side": "old"})
    database["bidRequests"].insert_one({"side": "new"})

    with pytest.raises(RuntimeError, match="both collections exist"):
        _run()

    # Nothing was destroyed, and the migration is not marked done.
    assert database["projects"].find_one({"side": "old"})
    assert database["bidRequests"].find_one({"side": "new"})
    assert database[migrations.LEDGER].count_documents({"_id": 1}) == 0


# ── m002: the audit envelope ────────────────────────────────────────────────


def test_m002_creates_the_organization_from_the_workbook(database) -> None:
    """Matrix 2.0 gives CBC's identity; it is not invented here."""
    from cbc.persistence.names import ORGANIZATIONS

    _run()

    org = database[ORGANIZATIONS].find_one({"slug": "cbc"})
    assert org["parent"] == "The Hamilton Parker Company"
    assert org["address"]["city"] == "Columbus"
    assert org["address"]["state"] == "OH"
    assert org["schemaVersion"] == 1


def test_m002_stamps_documents_that_predate_the_envelope(database) -> None:
    from cbc.persistence import envelope
    from cbc.persistence.names import BID_REQUESTS, OPENINGS, ORGANIZATIONS

    database["projects"].insert_one({"code": "CBC-260002", "slug": "test"})
    database["lineItems"].insert_one({"mark": "01", "size": "3070"})

    _run()

    org_id = database[ORGANIZATIONS].find_one({"slug": "cbc"})["_id"]
    for collection in (BID_REQUESTS, OPENINGS):
        row = database[collection].find_one({})
        assert row["orgId"] == org_id
        assert row["schemaVersion"] == envelope.SCHEMA_VERSION


def test_m002_indexes_the_tenant_filter(database) -> None:
    """§4.1's argument only holds if the filter is index-covered."""
    from cbc.persistence.names import BID_REQUESTS

    _run()
    assert "org" in database[BID_REQUESTS].index_information()


def test_m002_does_not_restamp_or_duplicate_on_a_second_run(database) -> None:
    from cbc.persistence.names import BID_REQUESTS, ORGANIZATIONS

    database["projects"].insert_one({"code": "CBC-260002", "slug": "test"})
    _run()

    stamped = database[BID_REQUESTS].find_one({})
    # A document that already carries an orgId is not matched again, so a
    # hand-corrected tenant would survive a re-run.
    database[BID_REQUESTS].update_one({"_id": stamped["_id"]}, {"$set": {"orgId": "kept"}})

    database[migrations.LEDGER].delete_one({"_id": 2})  # force a re-apply
    _run()

    assert database[ORGANIZATIONS].count_documents({"slug": "cbc"}) == 1
    assert database[BID_REQUESTS].find_one({})["orgId"] == "kept"


def test_m002_leaves_installation_wide_collections_alone(database) -> None:
    """settings and counters are keyed by name, one row per concern - not tenant data."""
    from cbc.persistence.names import COUNTERS, SETTINGS

    database[SETTINGS].insert_one({"_id": "claude", "mode": "ollama"})
    database[COUNTERS].insert_one({"_id": "projectCode", "seq": 7})

    _run()

    assert "orgId" not in database[SETTINGS].find_one({"_id": "claude"})
    assert "orgId" not in database[COUNTERS].find_one({"_id": "projectCode"})


# ── m003: the operational collections ───────────────────────────────────────


def test_m003_creates_the_four_missing_collections(database) -> None:
    """FR-12, FR-16, Phase 5 and FR-13 each had nowhere to store anything."""
    from cbc.persistence.migrations import m003_operational_collections as m003

    _run()

    present = set(database.list_collection_names())
    for collection in m003.CREATED:
        assert collection in present, f"{collection} was not created"


def test_m003_indexes_the_questions_each_collection_answers(database) -> None:
    from cbc.persistence.names import FEEDBACK_EVENTS, RFIS, VENDOR_RFQS

    _run()

    rfq = database[VENDOR_RFQS].index_information()
    assert rfq["rfq_number"].get("unique") is True
    assert "rfq_chase_list" in rfq, "what am I waiting on"
    assert "rfq_blocking" in rfq, "what is holding up the bid"

    assert "rfi_blocking" in database[RFIS].index_information()
    assert "feedback_by_type" in database[FEEDBACK_EVENTS].index_information()


def test_m003_leads_every_index_with_the_tenant(database) -> None:
    """§4.1: no collection has an index that omits orgId."""
    from cbc.persistence.migrations import m003_operational_collections as m003

    _run()
    for collection in m003.CREATED:
        for name, spec in database[collection].index_information().items():
            if name == "_id_":
                continue
            assert spec["key"][0][0] == "orgId", f"{collection}.{name} does not lead with orgId"
