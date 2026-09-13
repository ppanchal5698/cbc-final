"""ops: running the platform.

Sign-in and users, the audit trail, spend, and integration status - and, as the
remaining steps land, system settings, the job queue and the worker that drains
it. It owns `users`, `authAttempts`, `auditLogs` and `runMetrics`.

Other modules import only `cbc.modules.ops.api`. This file stays light: slices are
imported inside `register`, so a module that only wants `ops.api.audit` does not
load every HTTP handler.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount this module's routes on the application."""
    from cbc.modules.ops.features import (
        CreateUser,
        DeleteUser,
        GetMe,
        IntegrationStatus,
        ListAudit,
        ListUsers,
        SpendSummary,
        UpdateUser,
        VerifyCredentials,
    )

    for feature in (
        VerifyCredentials,
        GetMe,
        ListUsers,
        CreateUser,
        UpdateUser,
        DeleteUser,
        ListAudit,
        SpendSummary,
        IntegrationStatus,
    ):
        app.include_router(feature.router)


async def ensure_indexes() -> None:
    from cbc.modules.ops.infrastructure.collections import ensure_indexes as build

    await build()
