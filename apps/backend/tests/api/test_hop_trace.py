"""Hop X-Trace-Id middleware and enqueue stamping."""
from __future__ import annotations

import asyncio

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cbc.shared import tracing
from cbc.shared.tracing import TRACE_HEADER, TraceMiddleware


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "state": getattr(request.state, "trace_id", None),
            "current": tracing.current_trace_id(),
        }
    )


def _app() -> TestClient:
    app = Starlette(routes=[Route("/api/ping", _echo)])
    app.add_middleware(TraceMiddleware)
    return TestClient(app)


def test_middleware_mints_when_missing() -> None:
    client = _app()
    response = client.get("/api/ping")
    assert response.status_code == 200
    tid = response.headers.get(TRACE_HEADER)
    assert tid
    assert response.json()["state"] == tid


def test_middleware_preserves_inbound() -> None:
    client = _app()
    response = client.get("/api/ping", headers={TRACE_HEADER: "fixed-trace-99"})
    assert response.headers.get(TRACE_HEADER) == "fixed-trace-99"
    assert response.json()["state"] == "fixed-trace-99"
    assert response.json()["current"] == "fixed-trace-99"


def test_enqueue_copies_trace_id_top_level(monkeypatch) -> None:
    """traceId lands on the job doc, not inside payload (idempotency-safe)."""
    from bson import ObjectId

    captured: dict = {}

    class _Jobs:
        async def insert_one(self, job, session=None):
            captured.update(job)

            class _R:
                inserted_id = ObjectId()

            return _R()

        async def find_one(self, *a, **k):
            return None

        async def find_one_and_update(self, *a, **k):
            return None

    class _FakeDb:
        jobs = _Jobs()

    async def _audit(*_a, **_k):
        return None

    monkeypatch.setattr("cbc.services.jobs.db", _FakeDb())
    monkeypatch.setattr("cbc.services.jobs.audit.record", _audit)

    from cbc.services import jobs as job_service

    token = tracing.set_current_trace_id("hop-abc")
    try:
        job = asyncio.run(
            job_service.enqueue("ingest_pricebook", payload={"fileSha": "x"})
        )
    finally:
        tracing.reset_current_trace_id(token)

    assert captured.get("traceId") == "hop-abc"
    assert "traceId" not in (captured.get("payload") or {})
    assert job.get("traceId") == "hop-abc"
