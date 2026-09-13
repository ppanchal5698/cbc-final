"""Auth middleware and public Platform routes."""
from __future__ import annotations

import os

from cbc.shared.config import Settings


def test_protected_route_rejects_missing_token(client) -> None:
    response = client.get("/api/integrations")
    assert response.status_code == 401


def test_protected_route_accepts_token(client, auth_headers) -> None:
    response = client.get("/api/integrations", headers=auth_headers)
    assert response.status_code == 200
    assert "p21" in response.json()


def test_auth_verify_is_public(client) -> None:
    response = client.post("/api/auth/verify", json={})
    assert response.status_code in (400, 422)


def test_service_audience_defaults_platform() -> None:
    saved = os.environ.pop("SERVICE_AUDIENCE", None)
    try:
        settings = Settings()
        assert settings.service_audience == "platform"
    finally:
        os.environ["SERVICE_AUDIENCE"] = saved or "platform"
