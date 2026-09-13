"""Optional OpenTelemetry OTLP export (default off).

When OTEL_EXPORTER_OTLP_ENDPOINT is unset, configure() is a no-op and
tracer() returns a no-op tracer. Pytest and local compose stay quiet.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("cbc.otel")

_configured = False


def enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def configure(service_name: str | None = None) -> bool:
    """Install TracerProvider + OTLP HTTP exporter once. False when disabled."""
    global _configured
    if _configured:
        return enabled()
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        _configured = True
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("OTEL endpoint set but OpenTelemetry packages are not installed")
        _configured = True
        return False

    name = (
        service_name
        or os.environ.get("OTEL_SERVICE_NAME", "").strip()
        or "cbc-opshub"
    )
    resource = Resource.create({"service.name": name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    _configured = True
    log.info("OTLP tracing enabled for %s -> %s", name, endpoint)
    return True


def tracer(name: str = "cbc"):
    from opentelemetry import trace

    return trace.get_tracer(name)


@contextmanager
def span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Start a span when OTel is configured; otherwise yield None."""
    if not enabled():
        yield None
        return
    if not configure():
        yield None
        return
    tr = tracer()
    with tr.start_as_current_span(name) as current:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    current.set_attribute(key, value)
        yield current


def reset_for_tests() -> None:
    """Drop the configured flag so tests can flip the endpoint env."""
    global _configured
    _configured = False
