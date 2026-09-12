"""Re-export canonical settings for modular imports."""
from __future__ import annotations

from cbc.config import DEV_MONGO_PASSWORD, DEV_SECRET, Settings, get_settings, settings

__all__ = [
    "DEV_MONGO_PASSWORD",
    "DEV_SECRET",
    "Settings",
    "get_settings",
    "settings",
]
