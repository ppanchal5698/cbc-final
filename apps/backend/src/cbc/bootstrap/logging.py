"""Logging bootstrap — re-exports migrated core.logs."""
from __future__ import annotations

from cbc.core.logs import configure

__all__ = ["configure", "configure_logging"]


def configure_logging(level: str | None = None) -> None:
    import os

    name = "cbc.backend"
    configure(name)
    if level:
        import logging

        logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
    _ = os.environ.get("LOG_LEVEL")
