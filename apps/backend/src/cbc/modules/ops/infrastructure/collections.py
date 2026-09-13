"""The collections ops owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.ops.api`.
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from cbc.shared.persistence import names
from cbc.modules.ops.domain.jobs import EXCLUSIVE_JOB_TYPES
from cbc.shared.mongo import database, replace_index

# How long a failed sign-in stays counted. The TTL index below and
# VerifyCredentials' window both read it from here, so they cannot disagree.
AUTH_ATTEMPT_TTL = 300


def users():
    return database()[names.USERS]


def auth_attempts():
    return database()[names.AUTH_ATTEMPTS]


def audit_logs():
    return database()[names.AUDIT_LOGS]


def run_metrics():
    return database()[names.RUN_METRICS]


def settings_collection():
    return database()[names.SETTINGS]


def oauth_sessions():
    return database()[names.OAUTH_SESSIONS]


def jobs():
    return database()[names.JOBS]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, because m001 renames auditLog."""
    await users().create_index([("email", ASCENDING)], unique=True)
    await audit_logs().create_index([("at", DESCENDING)])
    await audit_logs().create_index([("target.projectId", ASCENDING)])
    # Sign-in attempts, counted across replicas rather than in one process. The
    # TTL is only garbage collection - `verify` filters on `at` itself, so the
    # window does not depend on when the background sweep last ran.
    await auth_attempts().create_index(
        [("at", ASCENDING)], name="attempt_ttl", expireAfterSeconds=AUTH_ATTEMPT_TTL
    )
    await auth_attempts().create_index([("email", ASCENDING), ("at", DESCENDING)])
    await run_metrics().create_index([("jobType", ASCENDING), ("startedAt", DESCENDING)])
    await run_metrics().create_index([("projectId", ASCENDING), ("startedAt", DESCENDING)])
    await run_metrics().create_index([("contextHashes.prompt", ASCENDING)])
    await run_metrics().create_index(
        [("outcome.errorCode", ASCENDING), ("startedAt", DESCENDING)]
    )
    await oauth_sessions().create_index(
        [("expiresAt", ASCENDING)], name="oauth_session_ttl", expireAfterSeconds=0
    )
    await jobs().create_index([("status", ASCENDING), ("createdAt", ASCENDING)])
    await jobs().create_index([("projectId", ASCENDING), ("createdAt", DESCENDING)])
    await replace_index(
        jobs(),
        "exclusive_active_job",
        [("projectId", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "status": {"$in": ["queued", "running"]},
            # One Claude session per bid: at most one active pipeline job per
            # project, regardless of type (autopilot must not overlap pricing).
            "type": {"$in": list(EXCLUSIVE_JOB_TYPES)},
        },
    )
    await replace_index(
        jobs(),
        "idempotency_active_job",
        [("idempotencyKey", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "status": {"$in": ["queued", "running"]},
            "idempotencyKey": {"$exists": True, "$type": "string"},
        },
    )
    await jobs().create_index([("status", ASCENDING), ("heartbeatAt", ASCENDING)])
    await jobs().create_index([("status", ASCENDING), ("finishedAt", DESCENDING)])
