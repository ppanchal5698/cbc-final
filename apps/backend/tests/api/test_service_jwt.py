"""Per-audience service JWTs for InternalAuthMiddleware."""
from __future__ import annotations

import time

import jwt
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cbc.shared.config import settings
from cbc.shared import service_jwt
from cbc.shared.auth import InternalAuthMiddleware
from tests.shared import TEST_ACTOR


@pytest.fixture()
def jwt_mode(monkeypatch):
    monkeypatch.setenv("INTERNAL_AUTH", "jwt")
    monkeypatch.setenv("SERVICE_AUDIENCE", "platform")
    monkeypatch.setenv("INTERNAL_JWT_SECRET", "wave2-jwt-secret")
    monkeypatch.delenv("INTERNAL_JWT_SECRET_PREVIOUS", raising=False)
    yield


async def _ok(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _mini_app() -> TestClient:
    app = Starlette(
        routes=[
            Route("/api/projects", _ok),
            Route("/api/health", _ok),
        ]
    )
    app.add_middleware(InternalAuthMiddleware)
    return TestClient(app)


def test_mint_and_verify_round_trip(jwt_mode) -> None:
    token = service_jwt.mint(TEST_ACTOR, "platform", secret="wave2-jwt-secret")
    claims = service_jwt.verify(token, audience="platform")
    assert claims["sub"] == TEST_ACTOR


def test_wrong_audience_is_rejected(jwt_mode) -> None:
    token = service_jwt.mint(TEST_ACTOR, "intake", secret="wave2-jwt-secret")
    with pytest.raises(jwt.InvalidAudienceError):
        service_jwt.verify(token, audience="platform")


def test_expired_token_is_rejected(jwt_mode) -> None:
    token = service_jwt.mint(
        TEST_ACTOR,
        "platform",
        secret="wave2-jwt-secret",
        ttl_seconds=1,
        now=int(time.time()) - 120,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        service_jwt.verify(token, audience="platform")


def test_previous_secret_still_verifies(jwt_mode, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_JWT_SECRET", "new-secret")
    monkeypatch.setenv("INTERNAL_JWT_SECRET_PREVIOUS", "wave2-jwt-secret")
    token = service_jwt.mint(TEST_ACTOR, "platform", secret="wave2-jwt-secret")
    claims = service_jwt.verify(token, audience="platform")
    assert claims["sub"] == TEST_ACTOR


def test_middleware_accepts_bearer_when_jwt_mode(jwt_mode) -> None:
    client = _mini_app()
    token = service_jwt.mint(TEST_ACTOR, "platform", secret="wave2-jwt-secret")
    response = client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_middleware_rejects_wrong_aud_when_jwt_mode(jwt_mode) -> None:
    client = _mini_app()
    token = service_jwt.mint(TEST_ACTOR, "catalog", secret="wave2-jwt-secret")
    response = client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_token_mode_still_works(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_AUTH", "token")
    monkeypatch.setattr(settings, "internal_api_token", "test-token")
    client = _mini_app()
    response = client.get(
        "/api/projects",
        headers={"X-Internal-Token": "test-token", "X-Actor": TEST_ACTOR},
    )
    assert response.status_code == 200
