"""Optional OTel module: no-op without endpoint; span attributes when stubbed."""
from __future__ import annotations

from cbc.http import otel, tracing
from cbc.http.tracing import TRACE_HEADER, TraceMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def test_otel_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel.reset_for_tests()
    assert otel.enabled() is False
    assert otel.configure("test") is False
    with otel.span("noop", attributes={"a": 1}) as span:
        assert span is None


def test_trace_middleware_still_works_without_otel(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel.reset_for_tests()

    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"trace": getattr(request.state, "trace_id", None)})

    app = Starlette(routes=[Route("/api/ping", ping)])
    app.add_middleware(TraceMiddleware)
    client = TestClient(app)
    response = client.get("/api/ping", headers={TRACE_HEADER: "wave4-trace"})
    assert response.status_code == 200
    assert response.headers.get(TRACE_HEADER) == "wave4-trace"
    assert response.json()["trace"] == "wave4-trace"


def test_span_sets_attribute_with_stub_tracer(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    otel.reset_for_tests()

    class _Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, key, value):
            self.attrs[key] = value

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Tracer:
        def start_as_current_span(self, name):
            return _Span()

    monkeypatch.setattr(otel, "configure", lambda *_a, **_k: True)
    monkeypatch.setattr(otel, "tracer", lambda *_a, **_k: _Tracer())
    with otel.span("unit", attributes={"cbc.trace_id": "t1"}) as span:
        assert span is not None
        assert span.attrs["cbc.trace_id"] == "t1"
