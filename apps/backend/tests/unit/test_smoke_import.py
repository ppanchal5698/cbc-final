"""Smoke: package and app factory import cleanly."""
from __future__ import annotations

from cbc.api.app import create_app


def test_create_app_imports() -> None:
    app = create_app()
    assert app.title == "CBC Estimating Copilot API"
    assert "monolith" in app.version
