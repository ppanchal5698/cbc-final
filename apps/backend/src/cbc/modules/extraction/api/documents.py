"""A port extraction needs and does not own: the bid's documents, which intake keeps.

An extract marks the documents it read - or failed on - and asks whether more
landed while it ran. intake owns documents and already depends on extraction, so
extraction cannot import it back: intake plugs its functions in here, from its
`register_jobs`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

_mark_received: Callable[..., Awaitable[int]] | None = None
_count_received_after: Callable[[Any, datetime | None], Awaitable[int]] | None = None


def bind(
    mark_received: Callable[..., Awaitable[int]],
    count_received_after: Callable[[Any, datetime | None], Awaitable[int]],
) -> None:
    global _mark_received, _count_received_after
    _mark_received, _count_received_after = mark_received, count_received_after


def _require() -> None:
    if _mark_received is None or _count_received_after is None:
        raise RuntimeError("no document port bound; intake binds it in register_jobs")


async def mark_received(project_id: Any, state: str, *, uploaded_by: datetime | None) -> int:
    """Move the bid's still-`received` documents, uploaded no later than `uploaded_by`, to `state`."""
    _require()
    return await _mark_received(project_id, state, uploaded_by=uploaded_by)


async def count_received_after(project_id: Any, uploaded_after: datetime | None) -> int:
    """Documents still `received` that landed after `uploaded_after` - a pass's stragglers."""
    _require()
    return await _count_received_after(project_id, uploaded_after)
