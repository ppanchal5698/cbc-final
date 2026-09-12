"""Platform projects route is registered (not a 501 stub)."""
from __future__ import annotations


def test_projects_list_requires_auth(client) -> None:
    response = client.get("/api/projects")
    assert response.status_code == 401


def test_projects_routes_registered(paths) -> None:
    assert "/api/projects" in paths or any(p.startswith("/api/projects") for p in paths)
    # Stub modules still expose documents; Platform owns CRUD on /api/projects
    assert any(p == "/api/projects" or p == "/api/projects/{code}" for p in paths)
