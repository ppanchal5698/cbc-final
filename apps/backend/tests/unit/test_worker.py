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
    from cbc.app.worker import main

    assert callable(main)


def test_the_catalog_local_jobs_are_registered(wired_worker) -> None:
    # Re-import after env is set (the loop computes CLAIMABLE_TYPES at import).
    import importlib

    from cbc.modules.ops.features import WorkerLoop

    importlib.reload(WorkerLoop)
    assert "index_catalog" in wired_worker._handlers
    assert "delete_catalog" in wired_worker._handlers
    assert callable(WorkerLoop.main)


def test_smoke_version_includes_monolith() -> None:
    from cbc.app.main import create_app

    assert "monolith" in create_app().version
