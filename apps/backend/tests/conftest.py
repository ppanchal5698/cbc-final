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
# worker_kit.runtime resolves CLAIMABLE_TYPES at import time.
os.environ.setdefault("WORKER_DOMAIN", "catalog")
# REFERENCE_DIR defaults to a repo-root `reference-library/` that exists only
# inside the image; a checkout keeps the seed JSON at `data/reference-library`.
# Must be set before anything imports cbc.config, which reads os.environ once at
# import. setdefault, so an in-container run (Dockerfile sets it) is untouched.
os.environ.setdefault("REFERENCE_DIR", "data/reference-library")

from tests.shared import FIXTURE_PDF, ROOT, direct_uri  # noqa: E402

# Reach the compose Mongo from the host, once, for every client the suite makes -
# pymongo in the fixtures and motor inside `cbc.db` alike. Fixing it per client
# was not enough before: a fixture connected, then `db.ensure_indexes()` built its
# own motor client from the untouched URI and failed anyway.
from cbc.config import settings  # noqa: E402

settings.mongodb_uri = direct_uri(settings.mongodb_uri)


@pytest.fixture(autouse=True)
def isolate_dotenv(tmp_path, monkeypatch):
    """Never let a test Save write the developer's real `.env`.

    `POST /api/settings/claude` rewrites the env file through
    `core.envfile.apply_to_environ`, so without this a settings test edits the
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

    monkeypatch.setattr("cbc.http.service_app.ensure_indexes", _ok)
    monkeypatch.setattr("cbc.http.service_app.ensure_readonly_user", _ok)
    monkeypatch.setattr("cbc.http.service_app.pageindex_store.ensure_indexes", _ok)

    # Refresh cached settings after forcing env above.
    from cbc import config

    config.get_settings.cache_clear()
    config.settings = config.get_settings()
    config.settings.mongodb_uri = direct_uri(config.settings.mongodb_uri)
    import cbc.http.deps as deps
    import cbc.http.service_app as service_app

    deps.settings = config.settings
    service_app.settings = config.settings

    from cbc.api.app import create_app

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
