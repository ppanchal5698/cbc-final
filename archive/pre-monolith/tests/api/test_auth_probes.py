"""The door, probed from outside.

`InternalAuthMiddleware` guarded the token comparison with `if token:`, so an
empty INTERNAL_API_TOKEN skipped it and authenticated anyone who sent an X-Actor
header - in every environment, silently. `config._assert_production_secrets` did
not catch it either, because an empty string is not the committed dev default.

These probe the middleware the way a caller would, rather than reading the
settings object and trusting it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cbc.config import settings
from tests.shared import TEST_ACTOR

PROBE_PATH = "/api/projects"
TEST_DB = "cbc_test_auth_probes"


@pytest.fixture(scope="module")
def client():
    from tests.shared import opshub_client

    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


def test_no_token_is_rejected(client: TestClient) -> None:
    response = client.get(PROBE_PATH, headers={"X-Internal-Token": ""})
    assert response.status_code == 401


def test_a_wrong_token_is_rejected(client: TestClient) -> None:
    response = client.get(PROBE_PATH, headers={"X-Internal-Token": "not-the-token"})
    assert response.status_code == 401


def test_no_actor_is_rejected(client: TestClient) -> None:
    """The token authenticates the Next.js server; X-Actor names the human."""
    response = client.get(PROBE_PATH, headers={"X-Actor": ""})
    assert response.status_code == 401


def test_the_actor_cannot_be_smuggled_through_the_query_string(
    client: TestClient,
) -> None:
    """`actor=` is ignored, so a direct caller cannot forge the audit trail."""
    response = client.get(
        f"{PROBE_PATH}?actor=someone.else@cbc.com",
        headers={"X-Actor": TEST_ACTOR},
    )
    assert response.status_code == 200


def test_health_stays_reachable_without_a_token(client: TestClient) -> None:
    """Public by design - a health check that needs a secret cannot be scraped."""
    response = client.get("/api/health", headers={"X-Internal-Token": ""})
    assert response.status_code == 200


def test_an_empty_configured_token_does_not_open_the_api(
    client: TestClient, monkeypatch
) -> None:
    """The regression this file exists for.

    With `if token:` in place this request succeeded: no secret configured, so no
    comparison made, so the caller was whoever it said it was.
    """
    monkeypatch.setattr(settings, "internal_api_token", "")
    response = client.get(PROBE_PATH, headers={"X-Internal-Token": ""})
    assert response.status_code == 401


def test_production_rejects_an_empty_token(monkeypatch) -> None:
    """And it never gets as far as serving a request."""
    from cbc.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "a-real-secret-from-secrets-manager")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "   ")
    monkeypatch.setenv("MONGODB_URI", "mongodb://cbc:s3cr3t@mongo:27017/cbc_opshub")

    with pytest.raises(RuntimeError, match="empty"):
        Settings()


# ── uploads stop at the limit rather than after it ──────────────────────────


def test_an_oversized_upload_is_cut_off_mid_stream(tmp_path) -> None:
    """The 413 the route returns depends on this raising, and on it raising early.

    `await file.read()` with no argument would pull the whole body into memory
    first, which makes the limit a report rather than a defence.
    """
    import asyncio
    import io

    from starlette.datastructures import UploadFile as StarletteUpload

    from cbc.services import storage

    limit = 1024
    body = io.BytesIO(b"%PDF-1.7" + b"x" * (limit * 4))
    upload = StarletteUpload(filename="big.pdf", file=body)
    target = tmp_path / "big.pdf"

    with pytest.raises(ValueError, match="exceeds"):
        asyncio.run(storage.receive_upload(upload, target, limit, magic=b"%PDF"))

    # And it must not leave the oversized part on disk.
    assert not target.exists() or target.stat().st_size <= limit


def test_a_non_pdf_is_refused_by_its_magic_bytes(tmp_path) -> None:
    import asyncio
    import io

    from starlette.datastructures import UploadFile as StarletteUpload

    from cbc.services import storage

    upload = StarletteUpload(filename="not.pdf", file=io.BytesIO(b"MZ\x90\x00hello"))
    with pytest.raises(ValueError):
        asyncio.run(
            storage.receive_upload(upload, tmp_path / "not.pdf", 1 << 20, magic=b"%PDF")
        )


def test_the_metrics_route_is_not_read_as_a_job_id(client: TestClient) -> None:
    """FastAPI matches in declaration order, so `/{job_id}` declared first would
    read this as a job whose id is the word "metrics" and 404."""
    response = client.get("/api/jobs/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "queued" in body and "failureRate" in body


def test_the_metrics_window_is_bounded(client: TestClient) -> None:
    """An unbounded `hours` is an unbounded aggregation over the whole collection."""
    assert client.get("/api/jobs/metrics?hours=99999").json()["windowHours"] == 24 * 30
    assert client.get("/api/jobs/metrics?hours=0").json()["windowHours"] == 1
