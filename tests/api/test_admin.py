"""Admin API: audit log and user management."""
from __future__ import annotations

import pytest

from tests.shared import TEST_ACTOR, opshub_client

TEST_DB = "cbc_opshub_test_admin"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, role="admin") as test_client:
        yield test_client


@pytest.fixture()
def as_role():
    from cbc.config import settings
    from pymongo import MongoClient

    raw = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)

    def set_role(role: str) -> None:
        raw[TEST_DB]["users"].update_one({"email": TEST_ACTOR}, {"$set": {"role": role}})

    try:
        yield set_role
    finally:
        set_role("admin")
        raw.close()


def test_estimator_cannot_read_audit_log(client, as_role) -> None:
    as_role("estimator")
    assert client.get("/api/audit").status_code == 403


def test_admin_can_read_audit_log(client, as_role) -> None:
    as_role("admin")
    response = client.get("/api/audit")
    assert response.status_code == 200
    assert "entries" in response.json()


def test_admin_can_list_users(client) -> None:
    response = client.get("/api/users")
    assert response.status_code == 200
    assert isinstance(response.json()["users"], list)


def test_estimator_cannot_list_users(client, as_role) -> None:
    as_role("estimator")
    assert client.get("/api/users").status_code == 403


def test_create_user(client) -> None:
    response = client.post(
        "/api/users",
        json={
            "email": "temp.admin@example.com",
            "name": "Temp Admin",
            "initials": "TA",
            "role": "estimator",
            "password": "opshub123",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "temp.admin@example.com"

    listed = client.get("/api/users").json()["users"]
    assert any(user["email"] == "temp.admin@example.com" for user in listed)

    user_id = response.json()["id"]
    client.delete(f"/api/users/{user_id}")


def test_health_reports_catalog_index_status(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["catalogIndex"] in {"ready", "missing"}
