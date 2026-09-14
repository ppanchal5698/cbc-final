"""Shared test helpers, ported from the pre-monolith suite.

The pre-monolith suite held 93 test files against the six-service tree.
The assertions are about business behaviour - margin snapshots, matching rules,
freshness bands, bbox provenance, proposal approval - and are worth more than
rewriting them would cost, so they come back module by module. This is the
harness they need.

Two things changed in the move:

- `ROOT` used to be the repo root because `tests/` sat there. It now comes from
  `cbc.shared.paths.repo_root()`, which walks up to a marker file, so the tests
  reach `.claude/`, `workflows/`, `docs/` and `templates/` wherever the suite is
  run from.
- `opshub_client` built its app from `tests.combined_app`, the harness that
  mounted six service apps into one. There is one app now, so it builds the real
  composition root.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest

from cbc.shared.paths import repo_root

ROOT = repo_root()

# Skill scripts are invoked as scripts, not imported as packages, so a few tests
# import them by bare name (`import parse_schedule`). `test_no_sys_path_insert`
# guards the installable trees and exempts tests/ for exactly this. Append, so
# nothing here can shadow a real package.
for _skill_scripts in (
    ROOT / ".claude" / "skills" / "extract-door-schedule" / "scripts",
    ROOT / ".claude" / "skills" / "generate-quotation" / "scripts",
):
    if _skill_scripts.is_dir() and str(_skill_scripts) not in sys.path:
        sys.path.append(str(_skill_scripts))

# Where the cutover moved things. The archived tests spelled these as
# `ROOT / "packages" / "cbc"`, `ROOT / "tests" / "fixtures"` and `ROOT / "docs"`,
# because tests/ and packages/ both sat at the repo root. Naming them once here
# means the next move edits this file and nothing else.
PKG = ROOT / "apps" / "backend" / "src" / "cbc"
FIXTURES = ROOT / "apps" / "backend" / "tests" / "fixtures"
# docs/ carries the architecture set and the requirements and rollout records.
DOCS = ROOT / "docs"

# The Dutch Bros bid set: the fixture the extraction tests read. Not committed
# (.dockerignore excludes tests/fixtures/pdfs/), so anything needing it skips.
FIXTURE_PDF = FIXTURES / "pdfs" / "1_Architectural.pdf"
SCHEDULE_PAGE = 14  # sheet A2.2

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
    and then cannot resolve it - whole modules skipped with "MongoDB is not
    reachable" against a container that was up and healthy. `directConnection`
    skips discovery and talks to the published port. Applied only to a loopback
    URI, so an in-container run is untouched.
    """
    from cbc.shared.mongo_uri import reachable_uri

    return reachable_uri(uri)


def mongo_client(**kwargs):
    """A pymongo client that can actually reach the compose Mongo."""
    from pymongo import MongoClient

    from cbc.shared.config import settings

    kwargs.setdefault("serverSelectionTimeoutMS", 5000)
    return MongoClient(direct_uri(settings.mongodb_uri), **kwargs)


def require_mongo(client) -> None:
    """Skip - or fail, under REQUIRE_MONGO - when the database is unreachable.

    This is the reader `REQUIRE_MONGO` lost. CI has set it since the monolith
    cutover and its comment says it converts a Mongo-unreachable skip into a
    failure, but the only code that honoured it was archived along with these
    tests, so the flag has been inert and the API suite has been stubbing Mongo
    out entirely.
    """
    from cbc.shared.config import settings

    try:
        client.server_info()
    except Exception as exc:
        where = settings.mongodb_uri.split("@")[-1]
        message = f"MongoDB is not reachable at {where}: {exc}"
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but {message}")
        pytest.skip(
            f"{message} - start it with "
            "`docker compose -f infra/docker-compose.yml up -d mongo`"
        )


@contextmanager
def opshub_client(
    db_name: str, *, isolated_storage: bool = False, role: str = "admin"
) -> Iterator["object"]:
    """A TestClient against a throwaway database, seeded with one actor."""
    from fastapi.testclient import TestClient

    from cbc.shared import mongo as db_module
    from cbc.app.main import create_app
    from cbc.shared.config import settings

    previous_db = settings.mongodb_db
    settings.mongodb_db = db_name
    db_module._client = None

    scratch: Path | None = None
    previous_storage = settings.storage_root
    previous_storage_env = os.environ.get("STORAGE_ROOT")
    if isolated_storage:
        scratch = ROOT / "apps" / "backend" / "tests" / "fixtures" / "scratch" / db_name
        scratch.mkdir(parents=True, exist_ok=True)
        settings.storage_root = scratch
        # Validation and review resolve projects through cbc.shared.paths, which
        # reads the environment rather than settings; both must name this scratch.
        os.environ["STORAGE_ROOT"] = str(scratch)

    raw = mongo_client()
    require_mongo(raw)
    raw.drop_database(db_name)
    raw[db_name]["users"].insert_one(
        {"email": TEST_ACTOR, "name": "Test Estimator", "role": role}
    )

    try:
        headers = {
            "X-Internal-Token": settings.internal_api_token,
            "X-Actor": TEST_ACTOR,
        }
        with TestClient(create_app(), headers=headers) as test_client:
            yield test_client
    finally:
        raw.drop_database(db_name)
        db_module._client = None
        raw.close()
        # Restored, like storage_root always was. Without it the first test to use
        # this left every later test pointed at a database it had just dropped.
        settings.mongodb_db = previous_db
        settings.storage_root = previous_storage
        if previous_storage_env is None:
            os.environ.pop("STORAGE_ROOT", None)
        else:
            os.environ["STORAGE_ROOT"] = previous_storage_env
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
