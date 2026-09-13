"""How a price book is shown: its age, and whether that makes it stale.

Staleness is surfaced rather than suppressed - NFR-10 has no named owner yet,
and pretending otherwise would hide the risk.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from cbc.modules.ops.api import freshness as freshness_settings
from cbc.shared.mongo import serialise


def _age_days(effective: str | None) -> int | None:
    if not effective:
        return None
    try:
        return (date.today() - date.fromisoformat(effective)).days
    except ValueError:
        return None


async def decorate(book: dict[str, Any]) -> dict[str, Any]:
    bands = await freshness_settings.load()
    age = _age_days(book.get("effective"))
    return {
        **serialise(book),
        "ageDays": age,
        "stale": age is not None and age > bands.catalog_stale_days,
        "undated": book.get("effective") is None,
    }
