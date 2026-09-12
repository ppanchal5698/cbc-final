"""Quoting quote/proposal routes are live (not 501 stubs)."""
from __future__ import annotations


def test_quote_requires_auth(client) -> None:
    response = client.get("/api/projects/CBC-0001/quote")
    assert response.status_code == 401


def test_proposal_requires_auth(client) -> None:
    response = client.get("/api/projects/CBC-0001/proposal")
    assert response.status_code == 401


def test_quote_and_proposal_routes_registered(app) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/projects/{code}/quote" in paths
    assert "/api/projects/{code}/proposal" in paths
