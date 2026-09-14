"""ops: running the platform.

Sign-in and users, the audit trail, spend, integration status and system
settings, the job queue and its routes, and the worker loop that drains it. It owns `users`, `authAttempts`, `auditLogs`, `runMetrics`,
`settings`, `oauthSessions` and `jobs`.

Other modules import only `cbc.modules.ops.api`. This file stays light: slices are
imported inside `register`, so a module that only wants `ops.api.audit` does not
load every HTTP handler.
"""
from __future__ import annotations

OAUTH_SWEEP_SECONDS = 60


def register(app) -> None:
    """Mount this module's routes on the application."""
    from cbc.modules.ops.features import (
        CancelJob,
        ClaudeOAuth,
        ClaudeSettings,
        CreateJob,
        CreateUser,
        DeleteUser,
        FreshnessSettings,
        GetJob,
        GetMe,
        GetTerminal,
        IntegrationStatus,
        JobMetrics,
        ListAudit,
        ListDeadJobs,
        ListJobs,
        ListOllamaModels,
        ListUsers,
        ParsingSettings,
        PipelineSettings,
        RetryJob,
        SpendSummary,
        StreamTerminal,
        TestClaudeSettings,
        TestParsingSettings,
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
        ParsingSettings,
        TestParsingSettings,
        ListOllamaModels,
        ClaudeOAuth,
        # Static /api/jobs paths before /api/jobs/{job_id}: routes match in the
        # order they are registered, so otherwise "metrics" is read as a job id.
        ListJobs,
        JobMetrics,
        ListDeadJobs,
        GetJob,
        CreateJob,
        CancelJob,
        RetryJob,
        GetTerminal,
        StreamTerminal,
    ):
        app.include_router(feature.router)


def run_worker() -> int:
    """The worker process: claim and run jobs until stopped. `python -m cbc.app.worker` calls this."""
    from cbc.modules.ops.features.WorkerLoop import main

    return main()


def background_jobs():
    """Periodic work this module needs while the API runs: (async callable, seconds)."""
    from cbc.modules.ops.features.ClaudeOAuth import sweep_oauth_sessions

    return [(sweep_oauth_sessions, OAUTH_SWEEP_SECONDS)]


async def ensure_indexes() -> None:
    from cbc.modules.ops.infrastructure.collections import ensure_indexes as build

    await build()
