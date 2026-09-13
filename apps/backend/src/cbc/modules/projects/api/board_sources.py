"""What the board shows that projects does not own, supplied by the modules that do.

projects may not import intake, because intake depends on projects. So intake
binds its document counts here when it registers, the way the composition root
binds ops' project lookup.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Counts = Callable[[list[Any]], Awaitable[dict[Any, int]]]

_document_counts: Counts | None = None


def bind_document_counts(source: Counts) -> None:
    global _document_counts
    _document_counts = source


async def document_counts(ids: list[Any]) -> dict[Any, int]:
    if _document_counts is None:
        raise RuntimeError("no document counts bound; intake binds them when it registers")
    return await _document_counts(ids)
