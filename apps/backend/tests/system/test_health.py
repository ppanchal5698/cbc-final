"""Health endpoint."""
from __future__ import annotations


def test_health_reachable(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "platform"
    assert body["status"] in ("ok", "degraded")
    assert body["sends"] == "disabled by design (NFR-1)"
