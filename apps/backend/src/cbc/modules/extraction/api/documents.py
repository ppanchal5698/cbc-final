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
_parse_signals: Callable[[Any, str], Awaitable[dict[str, Any]]] | None = None


def bind(
    mark_received: Callable[..., Awaitable[int]],
    count_received_after: Callable[[Any, datetime | None], Awaitable[int]],
    parse_signals: Callable[[Any, str], Awaitable[dict[str, Any]]] | None = None,
) -> None:
    global _mark_received, _count_received_after, _parse_signals
    _mark_received, _count_received_after = mark_received, count_received_after
    if parse_signals is not None:
        _parse_signals = parse_signals


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


async def parse_signals_by_path(project_id: Any, slug: str) -> dict[str, Any]:
    """Per raw-PDF page: whether the parser verified it, and how many blocks it read.

    Take-off routes a page to a vision read from this. Unbound or unparsed is the
    normal case on a fresh bid - the caller falls back to pdf-tools - so this
    answers `{}` rather than raising the way the two required ports do.
    """
    if _parse_signals is None:
        return {}
    return await _parse_signals(project_id, slug)
