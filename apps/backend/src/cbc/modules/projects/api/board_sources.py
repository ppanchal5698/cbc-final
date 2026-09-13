"""What the board shows that projects does not own, supplied by the modules that do.

projects may not import intake, extraction or quoting, because each depends on projects. So
each binds what it supplies here when it registers, the way the composition root
binds ops' project lookup.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Counts = Callable[[list[Any]], Awaitable[dict[Any, int]]]

OpeningCounts = Callable[[list[Any]], Awaitable[tuple[dict[Any, dict[str, int]], dict[Any, int]]]]

_document_counts: Counts | None = None
_opening_counts: OpeningCounts | None = None
Quotes = Callable[[list[Any]], Awaitable[dict[Any, dict[str, Any]]]]
_quotes: Quotes | None = None


def bind_document_counts(source: Counts) -> None:
    global _document_counts
    _document_counts = source


async def document_counts(ids: list[Any]) -> dict[Any, int]:
    if _document_counts is None:
        raise RuntimeError("no document counts bound; intake binds them when it registers")
    return await _document_counts(ids)


def bind_opening_counts(source: OpeningCounts) -> None:
    global _opening_counts
    _opening_counts = source


async def opening_counts(ids: list[Any]) -> tuple[dict[Any, dict[str, int]], dict[Any, int]]:
    """Per bid: openings by status, and how many are confirmed."""
    if _opening_counts is None:
        raise RuntimeError("no opening counts bound; extraction binds them when it registers")
    return await _opening_counts(ids)


def bind_quotes(source: Quotes) -> None:
    global _quotes
    _quotes = source


async def quotes(ids: list[Any]) -> dict[Any, dict[str, Any]]:
    """The stored quote for each bid, keyed by bid id."""
    if _quotes is None:
        raise RuntimeError("no quotes bound; quoting binds them when it registers")
    return await _quotes(ids)
