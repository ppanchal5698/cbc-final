"""Integration status endpoints."""
from __future__ import annotations

from tests.shared import opshub_client


def test_integrations_reports_p21_deferred() -> None:
    with opshub_client("test_integrations") as client:
        response = client.get("/api/integrations")
        assert response.status_code == 200
        payload = response.json()
        assert payload["p21"]["connected"] is False
        assert payload["p21"]["status"] == "deferred"
        assert "NR-10" in payload["p21"]["adminNote"]
        assert "NR-10" not in payload["p21"]["note"]
