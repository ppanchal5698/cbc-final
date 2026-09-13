"""A port ops needs and does not own: turning a project code into its id.

`GET /api/audit?project=` and `GET /api/jobs?project=` filter by bid. Bids belong
to the projects module, and projects already depends on ops - for the audit trail
and the job queue - so ops cannot import projects back without a cycle. ops
declares what it needs here; the composition root binds whoever owns bids.

A code that matches no bid raises whatever the binding raises; today that is the
404 the old shared lookup returned.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

_resolver: Callable[[str], Awaitable[Any]] | None = None
_summaries: Callable[[list[Any]], Awaitable[dict[Any, dict[str, Any]]]] | None = None


def bind(
    resolver: Callable[[str], Awaitable[Any]],
    summaries: Callable[[list[Any]], Awaitable[dict[Any, dict[str, Any]]]],
) -> None:
    global _resolver, _summaries
    _resolver = resolver
    _summaries = summaries


async def project_id(code_or_id: str) -> Any:
    if _resolver is None:
        raise RuntimeError("no project lookup bound; the composition root binds it in create_app")
    return await _resolver(code_or_id)


async def summaries(project_ids: list[Any]) -> dict[Any, dict[str, Any]]:
    """Code, name and slug for each of these bid ids, keyed by id."""
    if _summaries is None:
        raise RuntimeError("no project lookup bound; the composition root binds it in create_app")
    return await _summaries(project_ids)
