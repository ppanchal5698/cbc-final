"""Pytest fixtures for the modular monolith."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Force token mode for unit tests (do not use setdefault — shell may have jwt).
os.environ["INTERNAL_AUTH"] = "token"
os.environ["INTERNAL_API_TOKEN"] = "cbc-local-dev-key-change-me"
os.environ["INTERNAL_JWT_SECRET"] = "cbc-local-dev-key-change-me"
os.environ["SERVICE_AUDIENCE"] = "platform"
os.environ["APP_ENV"] = "development"
# worker_kit.runtime resolves CLAIMABLE_TYPES at import time.
os.environ.setdefault("WORKER_DOMAIN", "catalog")


@pytest.fixture
def app(monkeypatch):
    """Build app with Mongo/OAuth lifespan side effects stubbed out."""

    async def _ok(*_a, **_k):
        return True

    monkeypatch.setattr("cbc.http.service_app.ensure_indexes", _ok)
    monkeypatch.setattr("cbc.http.service_app.ensure_readonly_user", _ok)
    monkeypatch.setattr("cbc.http.service_app.pageindex_store.ensure_indexes", _ok)

    # Refresh cached settings after forcing env above.
    from cbc import config

    config.get_settings.cache_clear()
    config.settings = config.get_settings()
    import cbc.http.deps as deps
    import cbc.http.service_app as service_app

    deps.settings = config.settings
    service_app.settings = config.settings

    from cbc.api import app as app_module

    # Avoid OAuth sweep hitting Mongo during TestClient lifespan.
    original = app_module.create_app

    def _create_app_no_background():
        from cbc.http.service_app import create_service_app
        from cbc.modules.platform.api.router import router as platform_router
        from cbc.modules.catalog.api.router import router as catalog_router
        from cbc.modules.extraction.api.router import router as extraction_router
        from cbc.modules.intake.api.router import router as intake_router
        from cbc.modules.pricing.api.router import router as pricing_router
        from cbc.modules.quoting.api.router import router as quoting_router

        return create_service_app(
            name="platform",
            title="CBC Estimating Copilot API",
            routers=(
                platform_router,
                intake_router,
                extraction_router,
                pricing_router,
                quoting_router,
                catalog_router,
            ),
            background=(),
            version="0.9.1-monolith",
        )

    monkeypatch.setattr(app_module, "create_app", _create_app_no_background)
    return _create_app_no_background()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {
        "X-Internal-Token": "cbc-local-dev-key-change-me",
        "X-Actor": "admin@cbc.local",
    }
