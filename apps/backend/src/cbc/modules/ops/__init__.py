"""ops: running the platform.

Sign-in and users, the audit trail, spend, integration status and system
settings - and, as the remaining steps land, the job queue and the worker that
drains it. It owns `users`, `authAttempts`, `auditLogs`, `runMetrics`,
`settings` and `oauthSessions`.

Other modules import only `cbc.modules.ops.api`. This file stays light: slices are
imported inside `register`, so a module that only wants `ops.api.audit` does not
load every HTTP handler.
"""
from __future__ import annotations

OAUTH_SWEEP_SECONDS = 60


def register(app) -> None:
    """Mount this module's routes on the application."""
    from cbc.modules.ops.features import (
        ClaudeOAuth,
        ClaudeSettings,
        CreateUser,
        DeleteUser,
        FreshnessSettings,
        GetMe,
        IntegrationStatus,
        ListAudit,
        ListOllamaModels,
        ListUsers,
        PipelineSettings,
        SpendSummary,
        TestClaudeSettings,
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
        PipelineSettings,
        FreshnessSettings,
        ClaudeSettings,
        TestClaudeSettings,
        ListOllamaModels,
        ClaudeOAuth,
    ):
        app.include_router(feature.router)


def background_jobs():
    """Periodic work this module needs while the API runs: (async callable, seconds)."""
    from cbc.modules.ops.features.ClaudeOAuth import sweep_oauth_sessions

    return [(sweep_oauth_sessions, OAUTH_SWEEP_SECONDS)]


async def ensure_indexes() -> None:
    from cbc.modules.ops.infrastructure.collections import ensure_indexes as build

    await build()
