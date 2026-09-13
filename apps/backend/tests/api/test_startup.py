"""The checks that need no database.

Every other API test calls `opshub_client`, which skips when MongoDB is not
running - so a `SyntaxError` in a router imported by `api.main` produced a green
suite and a container that could not start. These run regardless.
"""
from __future__ import annotations

import compileall
import os

import pytest

from tests.shared import PKG, ROOT


def test_every_python_file_compiles() -> None:
    """A syntax error anywhere here means the API or the worker will not boot."""
    # These named api/ and worker/ at the repo root, which the cutover removed.
    # compile_dir returns success for a directory it cannot list, so the check
    # went on passing while compiling nothing of the live code.
    for package in (PKG.parent, ROOT / "apps" / "backend" / "scripts", ROOT / "mcp-servers", ROOT / "scripts"):
        assert package.is_dir(), f"{package} does not exist"
        assert compileall.compile_dir(
            str(package), quiet=2, force=True
        ), f"{package} does not compile"


def test_api_app_imports_with_its_routes() -> None:
    """`api.main` imports every router at module scope; one bad file breaks all of them.

    Asserted against the OpenAPI schema rather than `app.routes`, because how
    FastAPI stores an included router is an internal detail that has already
    changed once (0.141 keeps lazy wrappers where 0.115 flattened).
    """
    from cbc.app.main import create_app

    app = create_app(background=False)

    paths = set(app.openapi()["paths"])
    assert "/api/health" in paths
    # One route from the router whose syntax error stopped the whole app booting.
    assert "/api/projects/{code}/alternates/assign" in paths
    assert len(paths) > 40, f"only {len(paths)} paths registered"


# â”€â”€ uploaded filenames cannot escape their directory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../.claude/hooks/pre_send_quote.py",
        r"..\..\..\.claude\settings.json",
        "/etc/passwd",
        "....//....//evil.pdf",
        "..",
        "",
    ],
)
def test_upload_filename_stays_in_its_directory(tmp_path, hostile: str) -> None:
    from cbc.shared import storage

    target = storage.unique_filename(tmp_path, hostile)
    assert target.parent == tmp_path, f"{hostile!r} escaped to {target}"
    assert target.resolve().is_relative_to(tmp_path.resolve())


def test_ordinary_filename_survives_intact(tmp_path) -> None:
    from cbc.shared import storage

    assert storage.unique_filename(tmp_path, "Bid Set 25-073.pdf").name == "Bid Set 25-073.pdf"


# â”€â”€ the ingest handler will not read or delete outside .cache/ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_pricebook_ingest_refuses_a_path_outside_the_cache() -> None:
    import asyncio

    from cbc.modules.catalog.features.IngestPricebook import ingest_pricebook

    job = {
        "type": "ingest_pricebook",
        "payload": {"outputPath": "../../etc/passwd", "priceBookId": "0" * 24},
    }
    with pytest.raises(ValueError, match="must stay under"):
        asyncio.run(ingest_pricebook(job))


# â”€â”€ production refuses the committed development secrets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_production_rejects_the_default_secrets(monkeypatch) -> None:
    from cbc.shared.config import DEV_SECRET, Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", DEV_SECRET)
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="local-development"):
        Settings()


def test_production_starts_on_real_secrets(monkeypatch) -> None:
    from cbc.shared.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "a-real-secret-from-secrets-manager")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "another-real-secret")
    monkeypatch.setenv("MONGODB_URI", "mongodb://cbc:s3cr3t@mongo:27017/cbc_opshub")
    # The catalog server's read-only credential is checked too, and a production
    # deployment that leaves it at the repo default is exactly what that check is
    # for. Without it here the test asserted the opposite of what it says.
    monkeypatch.setenv("MONGODB_READONLY_PASSWORD", "a-real-readonly-secret")

    assert Settings().app_env == "production"


def test_development_keeps_working_with_no_configuration(monkeypatch) -> None:
    for name in ("APP_ENV", "APP_SECRET_KEY", "INTERNAL_API_TOKEN", "MONGODB_URI"):
        monkeypatch.delenv(name, raising=False)
    from cbc.shared.config import DEV_SECRET, Settings

    assert Settings().internal_api_token == DEV_SECRET


def test_the_seed_accounts_are_not_created_outside_development(monkeypatch):
    """admin@cbc.com / opshub is in this repository.

    docker/entrypoint.sh runs bootstrap.py whenever AUTO_BOOTSTRAP is not 0, and
    compose leaves it unset, so the first start of any deployment against an
    empty database created a known-password admin. _assert_production_secrets
    does not cover it - it gates secrets, not seeded accounts, and runs after.
    """
    from scripts.bootstrap import _may_seed_accounts

    for declared in ("production", "prod", "staging", "", "  "):
        monkeypatch.setenv("APP_ENV", declared)
        assert _may_seed_accounts() is False, declared

    monkeypatch.delenv("APP_ENV", raising=False)
    assert _may_seed_accounts() is False, "an undeclared environment must not seed"

    for declared in ("development", "DEV", " local "):
        monkeypatch.setenv("APP_ENV", declared)
        assert _may_seed_accounts() is True, declared

