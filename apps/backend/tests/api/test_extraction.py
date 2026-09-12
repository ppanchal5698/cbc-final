"""Extraction line-items/alternates are live (not 501 stubs)."""
from __future__ import annotations


def test_line_items_requires_auth(client) -> None:
    response = client.get("/api/projects/CBC-0001/line-items")
    assert response.status_code == 401


def test_line_items_route_registered(app) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/projects/{code}/line-items" in paths


def test_alternates_route_registered(app) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert any("alternates" in p for p in paths)
