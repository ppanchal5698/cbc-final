"""The collections ops owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.ops.api`.
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from cbc.shared.persistence import names
from cbc.modules.ops.domain.jobs import EXCLUSIVE_JOB_TYPES
from cbc.shared.mongo import create_index_resilient, database, replace_index

# How long a failed sign-in stays counted. The TTL index below and
# VerifyCredentials' window both read it from here, so they cannot disagree.
AUTH_ATTEMPT_TTL = 300
AI_ANSWER_TTL = 90 * 24 * 3600


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


def ai_answers():
    return database()[names.AI_ANSWERS]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, because m001 renames auditLog."""
    await users().create_index([("email", ASCENDING)], unique=True)
    await audit_logs().create_index([("at", DESCENDING)])
    # Cached answers to typed AI questions, keyed by the hash of question,
    # version and inputs. The TTL is only garbage collection.
    await create_index_resilient(
        ai_answers(), [("at", ASCENDING)], name="ai_answer_ttl", expireAfterSeconds=AI_ANSWER_TTL
    )
    await audit_logs().create_index([("target.projectId", ASCENDING)])
    # Sign-in attempts, counted across replicas rather than in one process. The
    # TTL is only garbage collection - `verify` filters on `at` itself, so the
    # window does not depend on when the background sweep last ran.
    # The named TTL indexes go through create_index_resilient: a database from an
    # earlier app carries the same keys as auto-named `at_1`, which a plain
    # create_index refuses (IndexOptionsConflict) and stops startup on.
    await create_index_resilient(
        auth_attempts(), [("at", ASCENDING)], name="attempt_ttl", expireAfterSeconds=AUTH_ATTEMPT_TTL
    )
    await auth_attempts().create_index([("email", ASCENDING), ("at", DESCENDING)])
    await run_metrics().create_index([("jobType", ASCENDING), ("startedAt", DESCENDING)])
    await run_metrics().create_index([("projectId", ASCENDING), ("startedAt", DESCENDING)])
    await run_metrics().create_index([("contextHashes.prompt", ASCENDING)])
    await run_metrics().create_index(
        [("outcome.errorCode", ASCENDING), ("startedAt", DESCENDING)]
    )
    await create_index_resilient(
        oauth_sessions(), [("expiresAt", ASCENDING)], name="oauth_session_ttl", expireAfterSeconds=0
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
            # $type alone: it never matches a missing field, so `$exists: True`
            # added nothing - and DocumentDB refuses two operators on one field
            # here as a nested $and.
            "idempotencyKey": {"$type": "string"},
        },
    )
    await jobs().create_index([("status", ASCENDING), ("heartbeatAt", ASCENDING)])
    await jobs().create_index([("status", ASCENDING), ("finishedAt", DESCENDING)])
