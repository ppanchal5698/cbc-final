"""Auth dependencies — re-export migrated http.deps."""
from __future__ import annotations

from cbc.http.deps import (
    ADMIN_ROLES,
    Actor,
    AdminActor,
    InternalAuthMiddleware,
    PUBLIC_PATHS,
    get_actor,
    require_admin,
)

__all__ = [
    "ADMIN_ROLES",
    "Actor",
    "AdminActor",
    "InternalAuthMiddleware",
    "PUBLIC_PATHS",
    "get_actor",
    "require_admin",
]
