"""In-process events between modules.

A module announces something that happened; other modules subscribe when the
application is composed. Same process, same request: handlers are awaited in the
order they subscribed, and an exception propagates to the publisher as it did
when the publisher made the call itself. No broker, no outbox, no retry.

It exists so a module can tell another without importing it - ops may not import
projects, because projects depends on ops, but projects can listen to ops.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[..., Awaitable[None]]

_subscribers: dict[str, list[Handler]] = {}


def subscribe(topic: str, handler: Handler) -> None:
    """Idempotent: the app is composed once per test, and a handler must not run twice."""
    handlers = _subscribers.setdefault(topic, [])
    if handler not in handlers:
        handlers.append(handler)


async def publish(topic: str, **payload: Any) -> None:
    for handler in list(_subscribers.get(topic, ())):
        await handler(**payload)
