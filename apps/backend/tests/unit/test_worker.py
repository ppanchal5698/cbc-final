"""Worker runtime is wired (not the Phase 0 no-op skeleton)."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _worker_domain(monkeypatch):
    monkeypatch.setenv("WORKER_DOMAIN", "catalog")
    # Ensure claimable types resolve at import without WORKER_CLAIM_ALL.
    os.environ["WORKER_DOMAIN"] = "catalog"


def test_worker_main_callable() -> None:
    from cbc.worker.main import main

    assert callable(main)


def test_worker_kit_local_handlers() -> None:
    # Re-import after env is set (module computes CLAIMABLE_TYPES at import).
    import importlib

    import cbc.worker_kit.runtime as runtime

    importlib.reload(runtime)
    assert "index_catalog" in runtime.LOCAL_HANDLERS
    assert "delete_catalog" in runtime.LOCAL_HANDLERS
    assert callable(runtime.main)


def test_smoke_version_includes_monolith() -> None:
    from cbc.app.main import create_app

    assert "monolith" in create_app().version
