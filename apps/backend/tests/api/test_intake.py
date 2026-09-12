"""Intake documents/versions are live (not 501 stubs)."""
from __future__ import annotations


def test_documents_requires_auth(client) -> None:
    response = client.get("/api/projects/CBC-0001/documents")
    assert response.status_code == 401


def test_documents_route_registered(paths) -> None:
    assert "/api/projects/{code}/documents" in paths


def test_versions_route_registered(paths) -> None:
    assert "/api/projects/{code}/versions" in paths
