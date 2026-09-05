"""Admin-only project delete with full Mongo and filesystem purge."""
from __future__ import annotations

import asyncio

import pytest
from bson import ObjectId
from pymongo import MongoClient

from cbc import db as db_module
from cbc.config import settings
from tests.shared import FIXTURE_PDF, TEST_ACTOR, opshub_client

TEST_DB = "cbc_opshub_test_project_delete"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True, role="admin") as test_client:
        yield test_client


@pytest.fixture()
def as_role():
    raw = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)

    def set_role(role: str) -> None:
        raw[TEST_DB]["users"].update_one({"email": TEST_ACTOR}, {"$set": {"role": role}})

    try:
        yield set_role
    finally:
        set_role("admin")
        raw.close()


def _create_project(client) -> dict:
    response = client.post("/api/projects", json={"name": "Delete purge test bid"})
    assert response.status_code == 201, response.text
    return response.json()


def _project_id(project: dict) -> ObjectId:
    return ObjectId(project["id"])


def test_an_estimator_cannot_delete_a_project(client, as_role) -> None:
    project = _create_project(client)
    as_role("estimator")

    response = client.delete(f"/api/projects/{project['code']}")

    assert response.status_code == 403
    assert "not permitted" in response.json()["detail"]
    assert client.get(f"/api/projects/{project['code']}").status_code == 200


def test_admin_delete_purges_mongo_and_disk(client) -> None:
    project = _create_project(client)
    project_id = _project_id(project)
    slug = project["slug"]
    code = project["code"]
    project_dir = settings.storage_root / slug
    assert project_dir.is_dir()

    if FIXTURE_PDF.exists():
        upload = client.post(
            f"/api/projects/{code}/documents",
            files={"file": (FIXTURE_PDF.name, FIXTURE_PDF.read_bytes(), "application/pdf")},
        )
        assert upload.status_code == 201, upload.text

    raw = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    database = raw[TEST_DB]
    try:
        assert database["projects"].count_documents({"_id": project_id}) == 1
        assert database["jobs"].count_documents({"projectId": project_id}) >= 1

        response = client.delete(f"/api/projects/{code}")
        assert response.status_code == 204, response.text

        for collection in (
            "projects",
            "documents",
            "lineItems",
            "quoteLines",
            "quotes",
            "proposals",
            "estimateVersions",
            "calls",
            "jobs",
        ):
            assert database[collection].count_documents({"projectId": project_id}) == 0

        assert database["projects"].count_documents({"_id": project_id}) == 0
        assert not project_dir.exists()
    finally:
        raw.close()


def test_admin_delete_removes_queued_job_history(client) -> None:
    from cbc.services.jobs import enqueue

    project = _create_project(client)
    project_id = _project_id(project)
    slug = project["slug"]

    async def queue_job():
        return await enqueue("extract_bid_set", project_id=project_id)

    db_module._client = None
    job = asyncio.run(queue_job())
    db_module._client = None

    raw = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    database = raw[TEST_DB]
    try:
        assert database["jobs"].count_documents({"_id": job["_id"]}) == 1
        assert client.delete(f"/api/projects/{project['code']}").status_code == 204
        assert database["jobs"].count_documents({"projectId": project_id}) == 0
        assert not (settings.storage_root / slug).exists()
    finally:
        raw.close()
