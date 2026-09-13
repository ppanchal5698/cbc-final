"""Pricing reference routes are live (not 501 stubs)."""
from __future__ import annotations


def test_reference_margins_requires_auth(client) -> None:
    response = client.get("/api/reference/margins")
    assert response.status_code == 401


def test_reference_route_registered(paths) -> None:
    assert "/api/reference/margins" in paths
