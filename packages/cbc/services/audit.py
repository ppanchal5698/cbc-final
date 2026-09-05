"""Audit trail (NFR-3).

Two actors touch this system - the estimator and Claude Code - and every change
either makes is recorded with who, what and when. Logging never blocks the
action it describes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from cbc.config import settings
from cbc.db import db

log = logging.getLogger("cbc.api.audit")


async def record(
    action: str,
    actor: str = "system",
    target: dict[str, Any] | None = None,
    before: Any = None,
    after: Any = None,
    note: str | None = None,
) -> None:
    try:
        await db.audit_log.insert_one(
            {
                "at": datetime.now(timezone.utc),
                "actor": actor,
                "action": action,
                "target": target or {},
                "before": before,
                "after": after,
                "note": note,
            }
        )
    except Exception:
        # A failed log must never fail the action it describes - but discarding it
        # without a trace leaves holes in the record NFR-3 exists to guarantee,
        # and nothing anywhere reports them. Say so, and keep the entry.
        log.exception("audit record lost from the database: %s by %s", action, actor)
        _write_fallback(action, actor, target, note)


def _write_fallback(action, actor, target, note) -> None:
    """Append the entry to disk when the database would not take it."""
    try:
        path = settings.storage_root / "_system" / "audit_fallback.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "actor": actor,
                        "action": action,
                        "target": target or {},
                        "note": note,
                        "reason": "database write failed",
                    },
                    default=str,
                )
                + "\n"
            )
    except Exception:
        log.exception("audit fallback file is unwritable too; entry is lost")
