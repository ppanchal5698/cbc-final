"""How a price book is shown: its age, and whether that makes it stale.

Staleness is surfaced rather than suppressed - NFR-10 has no named owner yet,
and pretending otherwise would hide the risk.

In local development, `lastReviewed` may drive staleness when set so stewards can
exercise fresh vs past-review states without rewriting the sheet's effective date.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from cbc.modules.ops.api import freshness as freshness_settings
from cbc.shared.mongo import serialise


def dev_freshness_controls() -> bool:
    """Whether price-book staleness can be toggled via review dates (dev only)."""
    explicit = os.environ.get("PRICEBOOK_DEV_FRESHNESS", "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    return os.environ.get("APP_ENV", "development").lower() not in (
        "production",
        "prod",
        "staging",
    )


def _staleness_reference(book: dict[str, Any]) -> tuple[str | None, str]:
    """Return the ISO date used for age and which field supplied it."""
    effective = book.get("effective")
    last_reviewed = book.get("lastReviewed")
    if dev_freshness_controls():
        if last_reviewed:
            return last_reviewed, "lastReviewed"
        if effective:
            return effective, "effective"
        return None, "lastReviewed"
    return effective, "effective"


def _age_days(reference: str | None) -> int | None:
    if not reference:
        return None
    try:
        return (date.today() - date.fromisoformat(reference)).days
    except ValueError:
        return None


async def decorate(book: dict[str, Any]) -> dict[str, Any]:
    bands = await freshness_settings.load()
    dev = dev_freshness_controls()
    reference, reference_field = _staleness_reference(book)
    age = _age_days(reference)
    undated = reference is None
    return {
        **serialise(book),
        "ageDays": age,
        "stale": age is not None and age > bands.catalog_stale_days,
        "undated": undated,
        "devFreshnessControls": dev,
        "staleReferenceField": reference_field,
        "staleReferenceDate": reference,
    }
