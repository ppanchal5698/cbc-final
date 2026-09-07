"""Shared test helpers imported by conftest and individual test modules."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]

# pytest.ini already puts services/* on pythonpath; `cbc` and `_runtime` come
# from editable installs. Skill scripts are not packages - load them by path.
for skill_scripts in (
    ROOT / ".claude" / "skills" / "extract-door-schedule" / "scripts",
    ROOT / ".claude" / "skills" / "generate-quotation" / "scripts",
):
    if skill_scripts.is_dir() and str(skill_scripts) not in sys.path:
        # Skill scripts are invoked as scripts; tests import them by bare name.
        # Keeping this off packages/services/mcp-servers/scripts trees.
        sys.path.append(str(skill_scripts))

FIXTURE_PDF = ROOT / "tests" / "fixtures" / "pdfs" / "1_Architectural.pdf"
SCHEDULE_PAGE = 14  # sheet A2.2 in the Dutch Bros fixture


TEST_ACTOR = "test@example.com"


def load_module(name: str, path: Path) -> ModuleType:
    """Import a free-standing .py file without editing sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def direct_uri(uri: str) -> str:
    """Reach a compose Mongo from the host.

    The single-node replica set advertises itself as `mongo:27017`, the name it
    has inside the compose network, so a driver on the host discovers that member
    and then cannot resolve it - the suite skipped with "MongoDB is not reachable"
    against a container that was up and healthy. `directConnection` skips
    discovery and talks to the port that is actually published. Only applied to a
    loopback URI, so an in-container run is untouched.
    """
    if "directConnection" in uri:
        return uri
    host = uri.split("@")[-1]
    if not host.startswith(("localhost", "127.0.0.1")):
        return uri
    return uri + ("&" if "?" in uri else "?") + "directConnection=true"



def mongo_client(**kwargs):
    """A pymongo client that can actually reach the compose Mongo.

    Nineteen call sites built `MongoClient(settings.mongodb_uri, ...)` by hand.
    Each one inherited the single-node replica-set problem `direct_uri` exists to
    solve, so whole test modules skipped with "MongoDB is not running" against a
    container that was up and healthy - and the tests inside them had never run.
    """
    from pymongo import MongoClient

    from cbc.config import settings

    kwargs.setdefault("serverSelectionTimeoutMS", 5000)
    return MongoClient(direct_uri(settings.mongodb_uri), **kwargs)

@contextmanager
def opshub_client(
    db_name: str, *, isolated_storage: bool = False, role: str = "admin"
) -> Iterator["object"]:
    from fastapi.testclient import TestClient
    from pymongo import MongoClient

    from cbc import db as db_module
    from cbc.config import settings
    from tests.combined_app import app

    settings.mongodb_db = db_name
    db_module._client = None

    scratch: Path | None = None
    previous_storage = settings.storage_root
    if isolated_storage:
        scratch = ROOT / "tests" / "fixtures" / "scratch" / db_name
        scratch.mkdir(parents=True, exist_ok=True)
        settings.storage_root = scratch

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception as exc:
        message = f"MongoDB is not reachable at {settings.mongodb_uri.split('@')[-1]}: {exc}"
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but {message}")
        pytest.skip(f"{message} - start it with `docker compose -f infra/docker-compose.yml up -d mongo`")
    raw.drop_database(db_name)

    raw[db_name]["users"].insert_one(
        {"email": TEST_ACTOR, "name": "Test Estimator", "role": role}
    )

    try:
        headers = {
            "X-Internal-Token": settings.internal_api_token,
            "X-Actor": TEST_ACTOR,
        }
        with TestClient(app, headers=headers) as test_client:
            yield test_client
    finally:
        raw.drop_database(db_name)
        db_module._client = None
        raw.close()
        settings.storage_root = previous_storage
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
