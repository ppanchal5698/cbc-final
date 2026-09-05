"""Job enqueue authorization — estimators may run pipeline work only."""
from __future__ import annotations

import pytest

from cbc.schemas.common import ESTIMATOR_JOB_TYPES
from tests.shared import TEST_ACTOR, opshub_client

TEST_DB = "cbc_opshub_test_job_authz"


# `client` and `as_role` are declared per-file across tests/api/ rather than in a
# conftest. This file asked for both and defined neither, so every test in it
# errored in setup with "fixture 'client' not found" - it had never once run.
@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, role="admin") as test_client:
        yield test_client


@pytest.fixture()
def as_role(client):
    from pymongo import MongoClient

    from cbc.config import settings

    raw = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)

    def set_role(role: str) -> None:
        raw[TEST_DB]["users"].update_one({"email": TEST_ACTOR}, {"$set": {"role": role}})

    try:
        yield set_role
    finally:
        set_role("admin")
        raw.close()


@pytest.mark.parametrize("job_type", sorted(ESTIMATOR_JOB_TYPES))
def test_estimators_may_enqueue_pipeline_jobs(client, as_role, job_type: str) -> None:
    as_role("estimator")
    response = client.post("/api/jobs", json={"type": job_type, "projectId": "DEMO-001"})
    assert response.status_code in (201, 404, 409), response.text


def test_estimators_cannot_enqueue_delete_catalog(client, as_role) -> None:
    as_role("estimator")
    response = client.post(
        "/api/jobs",
        json={"type": "delete_catalog", "payload": {"filename": "hager.pdf"}},
    )
    assert response.status_code == 403


def test_admins_may_enqueue_delete_catalog(client, as_role) -> None:
    as_role("admin")
    response = client.post(
        "/api/jobs",
        json={"type": "delete_catalog", "payload": {"filename": "hager.pdf"}},
    )
    assert response.status_code == 201, response.text
