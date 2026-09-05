"""Shared fixtures and path wiring for the CBC test suite."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Domain workers set WORKER_DOMAIN at process start. Tests import the runtime
# module at collection time, which fail-closes without one of these.
os.environ.setdefault("WORKER_CLAIM_ALL", "1")

import tests.shared  # noqa: F401  — sets sys.path for MCP servers
from _runtime import load_server  # noqa: E402
from tests.shared import FIXTURE_PDF, ROOT, SCHEDULE_PAGE


@pytest.fixture(autouse=True)
def isolate_dotenv(tmp_path, monkeypatch):
    """Never let a test Save write the developer's real `.env`."""
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
    return load_server("calc-engine")


@pytest.fixture(scope="session")
def catalog():
    return load_server("catalog")


@pytest.fixture(scope="session")
def p21():
    return load_server("p21-connector")
