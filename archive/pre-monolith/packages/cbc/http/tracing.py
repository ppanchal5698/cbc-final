"""Hop tracing via X-Trace-Id, with optional OTLP span when configured.

Each API request accepts or mints a UUID; the middleware stores it on
request.state, a contextvar (for enqueue), and the response header. Workers
bind the job's top-level traceId into structured logs.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from cbc.http import otel

TRACE_HEADER = "X-Trace-Id"

_current: ContextVar[str | None] = ContextVar("cbc_trace_id", default=None)


def mint() -> str:
    return str(uuid.uuid4())


def current_trace_id() -> str | None:
    return _current.get()


def set_current_trace_id(trace_id: str | None):
    """Return a contextvars token; caller must reset."""
    return _current.set(trace_id)


def reset_current_trace_id(token) -> None:
    _current.reset(token)


def normalize(raw: str | None) -> str:
    value = (raw or "").strip()
    return value if value else mint()


class TraceMiddleware(BaseHTTPMiddleware):
    """Mint or propagate X-Trace-Id on every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        trace_id = normalize(request.headers.get(TRACE_HEADER))
        request.state.trace_id = trace_id
        token = set_current_trace_id(trace_id)
        try:
            with otel.span(
                f"http {request.method} {request.url.path}",
                attributes={
                    "cbc.trace_id": trace_id,
                    "http.method": request.method,
                    "http.route": request.url.path,
                },
            ):
                response = await call_next(request)
        finally:
            reset_current_trace_id(token)
        response.headers[TRACE_HEADER] = trace_id
        return response
