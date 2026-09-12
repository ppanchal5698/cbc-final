#!/usr/bin/env python3
"""One-shot adversarial probes for QA audit evidence."""
from __future__ import annotations

import json
import sys

from fastapi.testclient import TestClient
from pymongo import MongoClient

from cbc.config import settings

# One app again, after the monolith cutover. This used to import
# `tests.combined_app`, the pre-cutover harness that mounted six service apps
# into one - which now exists only under archive/pre-monolith/, so the script
# could not run at all. Probe the real composition root instead.
from cbc.api.app import create_app

app = create_app()

TOKEN = settings.internal_api_token
HEADERS = {"X-Internal-Token": TOKEN, "X-Actor": "estimator@cbc.com"}


def main() -> int:
    raw = MongoClient(settings.mongodb_uri)
    db = raw[settings.mongodb_db]
    print("users_in_db", db["users"].count_documents({}))

    client = TestClient(app, headers=HEADERS)

    # Login (public)
    pub = TestClient(app)
    login = pub.post(
        "/api/auth/verify",
        json={"email": "estimator@cbc.com", "password": "opshub"},
    )
    print("login_seed_user", login.status_code, login.text[:120])

    # Assign JSON object (frontend path)
    project = client.post("/api/projects", json={"name": "QA Probe", "state": "OH"}).json()
    code = project["code"]
    client.post(f"/api/projects/{code}/alternates", json={"name": "Alt A"})
    assign_obj = client.post(
        f"/api/projects/{code}/alternates/assign",
        json={"ids": ["507f1f77bcf86cd799439011"], "alternate": "Alt A", "scope": "line-items"},
    )
    print("assign_json_object", assign_obj.status_code, assign_obj.text[:160])

    assign_empty = client.post(
        f"/api/projects/{code}/alternates/assign",
        json={"ids": [], "alternate": "Alt A"},
    )
    print("assign_empty_ids", assign_empty.status_code, assign_empty.text)

    limit_neg = client.get("/api/projects?limit=-1")
    print("projects_limit_neg1", limit_neg.status_code, limit_neg.text[:160])

    # Duplicate exclusive job returns 201
    p = client.post("/api/projects", json={"name": "Job Dedup"}).json()
    j1 = client.post(
        "/api/jobs",
        json={"type": "extract_bid_set", "projectId": p["code"]},
    )
    j2 = client.post(
        "/api/jobs",
        json={"type": "extract_bid_set", "projectId": p["code"]},
    )
    print(
        "duplicate_job",
        j1.status_code,
        j2.status_code,
        j1.json().get("id") == j2.json().get("id"),
    )

    # Auth rate limit
    for i in range(12):
        r = pub.post(
            "/api/auth/verify",
            json={"email": "ratelimit@example.com", "password": "wrong"},
        )
    print("rate_limit_last", r.status_code, r.text[:80])

    raw.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
