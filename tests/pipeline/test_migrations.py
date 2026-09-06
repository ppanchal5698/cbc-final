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
        yield raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def _pending() -> list:
    from cbc import db as db_module

    db_module._client = None
    try:
        return asyncio.run(migrations.pending(db_module.database()))
    finally:
        db_module._client = None


def _run() -> list:
    """Apply pending migrations against the database settings currently name."""
    from cbc import db as db_module

    db_module._client = None
    try:
        return asyncio.run(migrations.run())
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
