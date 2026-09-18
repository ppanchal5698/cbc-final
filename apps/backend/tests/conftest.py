"""Pytest fixtures for the modular monolith."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Force token mode for unit tests (do not use setdefault — shell may have jwt).
os.environ["INTERNAL_AUTH"] = "token"
os.environ["INTERNAL_API_TOKEN"] = "cbc-local-dev-key-change-me"
os.environ["INTERNAL_JWT_SECRET"] = "cbc-local-dev-key-change-me"
os.environ["SERVICE_AUDIENCE"] = "platform"
os.environ["APP_ENV"] = "development"
# ops' worker loop (WorkerLoop) resolves CLAIMABLE_TYPES once, at import.
# WORKER_CLAIM_ALL=1 claims every domain except `parsing` (dedicated GPU worker).
# Parse-document tests call the handler directly rather than through claim().
# This was WORKER_DOMAIN=catalog, which scoped `claim()` to catalog jobs for the
# whole process, so test_recovery's backoff test could never claim the
# extract_bid_set job it queued. tests/modules/ops/test_worker.py sets its own
# domain and reloads.
os.environ.setdefault("WORKER_CLAIM_ALL", "1")
# The data directories default to the checkout layout (cbc.shared.paths). Pinned
# here too, so a developer .env naming another directory cannot redirect the suite;
# setdefault, so an in-container run (the Dockerfile sets them) is untouched.
os.environ.setdefault("REFERENCE_DIR", "data/reference-library")
os.environ.setdefault("PRICEBOOK_DIR", "data/pricebooks")
# The test process never talks to the dev database. MONGODB_DB defaults to
# `cbc_opshub` in config.py, compose and .env.example, so any test that reached
# Mongo without switching databases wrote there - test_authorization's
# `_clear_attempts` runs `delete_many({})` on `authAttempts` in whatever
# `settings.mongodb_db` names. Assigned, not setdefault: a shell that exported
# MONGODB_DB=cbc_opshub must not win.
DEV_DB = "cbc_opshub"
os.environ["MONGODB_DB"] = "cbc_opshub_pytest"

from tests.shared import FIXTURE_PDF, ROOT, direct_uri  # noqa: E402

# Reach the compose Mongo from the host, once, for every client the suite makes -
# pymongo in the fixtures and motor inside `cbc.shared.mongo` alike. Fixing it per client
# was not enough before: a fixture connected, then the startup index build made its
# own motor client from the untouched URI and failed anyway.
from cbc.shared.config import settings  # noqa: E402

settings.mongodb_uri = direct_uri(settings.mongodb_uri)
assert settings.mongodb_db != DEV_DB, (
    f"the test process resolved MONGODB_DB to {DEV_DB!r}, the dev database; "
    "something imported cbc.shared.config before this conftest forced it"
)


@pytest.fixture(autouse=True)
def isolate_dotenv(tmp_path, monkeypatch):
    """Never let a test Save write the developer's real `.env`.

    `POST /api/settings/claude` rewrites the env file through
    `shared.envfile.apply_to_environ`, so without this a settings test edits the
    working tree.
    """
    monkeypatch.setenv("CBC_ENV_FILE", str(tmp_path / ".env"))


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def fixture_pdf() -> Path:
    if not FIXTURE_PDF.exists():
        pytest.skip(f"test fixture not present: {FIXTURE_PDF}")
    return FIXTURE_PDF


@pytest.fixture(scope="session")
def calc():
    from _runtime import load_server

    return load_server("calc-engine")


@pytest.fixture(scope="session")
def catalog():
    from _runtime import load_server

    return load_server("catalog")


@pytest.fixture(scope="session")
def p21():
    from _runtime import load_server

    return load_server("p21-connector")


@pytest.fixture
def app(monkeypatch):
    """The real composition root, with Mongo/OAuth lifespan side effects stubbed.

    This used to rebuild `create_app` inline to drop the background sweep, so the
    suite exercised a different app than production - and that copy said version
    "0.9.1-monolith" against the real "0.10.0". `create_app(background=False)`
    is the same object the process serves, minus the one periodic task.
    """

    async def _ok(*_a, **_k):
        return True

    monkeypatch.setattr("cbc.app.main.migrate_and_index", _ok)
    monkeypatch.setattr("cbc.app.main.ensure_readonly_user", _ok)
    monkeypatch.setattr("cbc.app.main.pageindex_store.ensure_indexes", _ok)

    # No settings refresh here. This fixture used to rebuild `cbc.shared.config.settings`
    # and assign the new object onto config, http.deps and http.service_app -
    # directly, never restored. Every module that had already done
    # `from cbc.shared.config import settings` (shared.storage, shared.storage_backends,
    # worker_kit.sandbox) kept the old object, so any later test that set
    # `settings.storage_root` patched the new one while the code under test read
    # the old: five tests in pipeline/ and api/test_service_jwt passed alone and
    # failed after any test that used `client`. The env is forced at the top of
    # this file before anything imports cbc.shared.config, so the original object was
    # already correct and there was nothing to refresh.
    from cbc.app.main import create_app

    return create_app(background=False)


@pytest.fixture
def paths(app):
    """Every path the app publishes.

    Eight tests each built this themselves as
    `{getattr(route, "path", "") for route in app.routes}`. FastAPI 0.141 stopped
    flattening `include_router` into `app.routes` - included routers now appear
    as opaque `_IncludedRouter` entries with no `.path` - so all eight silently
    narrowed to {"", "/api/health", "/docs", ...} and started failing. The
    OpenAPI schema is the app's own answer to "what do you serve", is what CI
    already counts, and does not move with the router internals.
    """
    return frozenset(app.openapi()["paths"])


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {
        "X-Internal-Token": "cbc-local-dev-key-change-me",
        "X-Actor": "admin@cbc.local",
    }


@pytest.fixture
def wired_worker(monkeypatch):
    """The worker's composition root wired - ops' job registry, the ports it fills and
    the event subscriptions are put back afterwards, so no later test finishes a job
    into real hooks."""
    from cbc.modules.extraction.api import documents
    from cbc.modules.ops.api import worker
    from cbc.app import worker as main
    from cbc.shared import events

    for name, empty in (("_handlers", {}), ("_after", {}), ("_after_finish", None), ("_on_dead", None)):
        monkeypatch.setattr(worker, name, empty)
    for name in ("_mark_received", "_count_received_after"):
        monkeypatch.setattr(documents, name, None)
    monkeypatch.setattr(events, "_subscribers", {topic: list(heard) for topic, heard in events._subscribers.items()})
    main.wire()
    return worker
