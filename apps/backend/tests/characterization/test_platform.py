"""Platform module: health, auth, users, projects, jobs, settings, calls and ops.

Three routes reach outside the process, and each is pinned on a path that does
not: `claude/test` runs the Claude CLI (preflight is stubbed), `ollama/models`
calls a model host (a URL the allowlist rejects never leaves), and
`claude/oauth/start` needs a pty and the CLI (a stand-in pty module and no CLI
give the same answer on Windows and Linux).
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

import pytest

from tests.characterization._harness import finish_pipeline_jobs
from tests.shared import TEST_ACTOR, mongo_client, opshub_client

TEST_DB = "cbc_opshub_char_platform"
ESTIMATOR = {"email": "char.estimator@example.com", "name": "Char Estimator", "initials": "CE",
             "role": "estimator", "password": "correct horse battery staple"}


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True, role="admin") as test_client:
        yield test_client


@pytest.fixture(scope="module")
def state() -> dict:
    return {}


def test_health(client, snapshots) -> None:
    response = snapshots.pin("GET /api/health", client.get("/api/health"))
    assert response.json()["catalogIndex"] in {"ready", "missing"}


# ── users and auth ───────────────────────────────────────────────────────────


def test_create_a_user(client, state, snapshots) -> None:
    op = "POST /api/users"
    response = snapshots.pin(op, client.post("/api/users", json=ESTIMATOR))
    state["user"] = response.json()["id"]
    snapshots.pin(op, client.post("/api/users", json=ESTIMATOR), variant="already registered")


def test_list_users(client, state, snapshots) -> None:
    response = snapshots.pin("GET /api/users", client.get("/api/users"))
    state["me"] = next(u["id"] for u in response.json()["users"] if u["email"] == TEST_ACTOR)


def test_verify_a_password(client, snapshots) -> None:
    op = "POST /api/auth/verify"
    body = {"email": ESTIMATOR["email"], "password": ESTIMATOR["password"]}
    snapshots.pin(op, client.post("/api/auth/verify", json=body))
    snapshots.pin(op, client.post("/api/auth/verify", json={**body, "password": "wrong"}), variant="wrong password")


def test_who_am_i(client, snapshots) -> None:
    op = "GET /api/auth/me/{email}"
    snapshots.pin(op, client.get(f"/api/auth/me/{ESTIMATOR['email']}"))
    snapshots.pin(op, client.get("/api/auth/me/nobody@example.com"), variant="unknown email")


def test_update_a_user(client, state, snapshots) -> None:
    op = "PATCH /api/users/{user_id}"
    snapshots.pin(op, client.patch(f"/api/users/{state['user']}", json={"initials": "CX"}))
    snapshots.pin(op, client.patch("/api/users/" + "0" * 24, json={"initials": "CX"}), variant="missing user")


def test_delete_a_user(client, state, snapshots) -> None:
    op = "DELETE /api/users/{user_id}"
    snapshots.pin(op, client.delete(f"/api/users/{state['me']}"), variant="own account")
    snapshots.pin(op, client.delete(f"/api/users/{state['user']}"))


# ── projects ─────────────────────────────────────────────────────────────────


def test_create_projects(client, state, snapshots) -> None:
    body = {"name": "Char platform bid", "brand": "Burger King", "gc": "Char GC", "state": "OH", "initiator": "Rick Sales"}
    response = snapshots.pin("POST /api/projects", client.post("/api/projects", json=body))
    state["prior"] = response.json()["code"]
    second = client.post("/api/projects", json={**body, "name": "Char platform repeat bid"})
    assert second.status_code == 201, second.text
    state["code"] = second.json()["code"]


def test_list_projects(client, snapshots) -> None:
    snapshots.pin("GET /api/projects", client.get("/api/projects", params={"q": "Char platform", "limit": 10}))


def test_get_a_project(client, state, snapshots) -> None:
    op = "GET /api/projects/{code}"
    snapshots.pin(op, client.get(f"/api/projects/{state['code']}"))
    snapshots.pin(op, client.get("/api/projects/CBC-999999"), variant="missing project")


def test_update_a_project(client, state, snapshots) -> None:
    snapshots.pin("PATCH /api/projects/{code}", client.patch(f"/api/projects/{state['code']}", json={"architect": "Char Architect"}))


def test_prior_quotes_and_reuse(client, state, snapshots) -> None:
    response = snapshots.pin("GET /api/projects/{code}/prior-quotes", client.get(f"/api/projects/{state['code']}/prior-quotes"))
    assert state["prior"] in {p["code"] for p in response.json()["priors"]}
    op = "POST /api/projects/{code}/reuse/{prior_code}"
    snapshots.pin(op, client.post(f"/api/projects/{state['code']}/reuse/{state['prior']}"))
    snapshots.pin(op, client.post(f"/api/projects/{state['code']}/reuse/CBC-999999"), variant="missing prior")


# ── calls and notes ──────────────────────────────────────────────────────────


def test_calls(client, state, snapshots) -> None:
    base = f"/api/projects/{state['code']}/calls"
    snapshots.pin("GET /api/projects/{code}/calls", client.get(base))
    note = snapshots.pin("POST /api/projects/{code}/calls", client.post(base, json={"kind": "note", "text": "Called GC about 05"}))
    rfi = client.post(base, json={"kind": "rfi", "text": "Rating for 05?"})
    assert rfi.status_code == 201, rfi.text

    op = "POST /api/projects/{code}/calls/{call_id}/resolve"
    snapshots.pin(op, client.post(f"{base}/{rfi.json()['id']}/resolve"))
    snapshots.pin(op, client.post(f"{base}/{note.json()['id']}/resolve"), variant="not an rfi")

    op = "DELETE /api/projects/{code}/calls/{call_id}"
    snapshots.pin(op, client.delete(f"{base}/{note.json()['id']}"))
    snapshots.pin(op, client.delete(f"{base}/{note.json()['id']}"), variant="already deleted")


# ── jobs ─────────────────────────────────────────────────────────────────────


def test_enqueue_a_job(client, state, snapshots) -> None:
    op = "POST /api/jobs"
    response = snapshots.pin(op, client.post("/api/jobs", json={"type": "index_catalog", "payload": {}}))
    state["job"] = response.json()["id"]
    snapshots.pin(op, client.post("/api/jobs", json={"type": "run_full_pipeline"}), variant="retired type")


def test_list_jobs(client, state, snapshots) -> None:
    op = "GET /api/jobs"
    snapshots.pin(op, client.get("/api/jobs", params={"limit": 5}))
    snapshots.pin(op, client.get("/api/jobs", params={"pipeline_active": True}), variant="pipeline_active without project")


def test_job_metrics(client, snapshots) -> None:
    snapshots.pin("GET /api/jobs/metrics", client.get("/api/jobs/metrics", params={"hours": 24}))


def test_get_a_job(client, state, snapshots) -> None:
    op = "GET /api/jobs/{job_id}"
    snapshots.pin(op, client.get(f"/api/jobs/{state['job']}"))
    snapshots.pin(op, client.get("/api/jobs/" + "0" * 24), variant="missing job")


def test_cancel_a_job(client, state, snapshots) -> None:
    op = "POST /api/jobs/{job_id}/cancel"
    snapshots.pin(op, client.post(f"/api/jobs/{state['job']}/cancel"))
    snapshots.pin(op, client.post(f"/api/jobs/{state['job']}/cancel"), variant="already cancelled")


def test_dead_letters_and_retry(client, state, snapshots) -> None:
    raw = mongo_client()
    try:
        now = datetime.now(timezone.utc)
        dead = raw[TEST_DB].jobs.insert_one(
            {"type": "index_catalog", "status": "dead", "attempts": 3, "projectId": None,
             "payload": {}, "createdAt": now, "finishedAt": now, "error": "characterization"}
        ).inserted_id
    finally:
        raw.close()

    snapshots.pin("GET /api/jobs/dead", client.get("/api/jobs/dead", params={"limit": 5}))
    op = "POST /api/jobs/{job_id}/retry"
    snapshots.pin(op, client.post(f"/api/jobs/{dead}/retry"))
    snapshots.pin(op, client.post(f"/api/jobs/{state['job']}/retry"), variant="cancelled job")


def test_terminal_of_a_finished_job(client, state, snapshots) -> None:
    response = snapshots.pin("GET /api/jobs/{job_id}/terminal", client.get(f"/api/jobs/{state['job']}/terminal"))
    assert response.json()["available"] is False
    stream = snapshots.pin("GET /api/jobs/{job_id}/terminal/stream", client.get(f"/api/jobs/{state['job']}/terminal/stream"))
    assert "event: end" in stream.text


# ── settings ─────────────────────────────────────────────────────────────────


def test_pipeline_settings(client, snapshots) -> None:
    snapshots.pin("GET /api/settings/pipeline", client.get("/api/settings/pipeline"))
    snapshots.pin("PUT /api/settings/pipeline", client.put("/api/settings/pipeline", json={"autopilotDefault": False}))


def test_freshness_settings(client, snapshots) -> None:
    snapshots.pin("GET /api/settings/freshness", client.get("/api/settings/freshness"))
    op = "PUT /api/settings/freshness"
    snapshots.pin(op, client.put("/api/settings/freshness", json={"catalogStaleMonths": 24, "discardAfterMonths": 36}))
    snapshots.pin(op, client.put("/api/settings/freshness", json={"catalogStaleMonths": 48, "discardAfterMonths": 36}), variant="review window beyond discard")
    snapshots.pin(op, client.put("/api/settings/freshness", json={"catalogStaleMonths": 24, "discardAfterMonths": 12, "freshMonths": 12}), variant="discard before fresh")


def test_claude_settings(client, snapshots) -> None:
    snapshots.pin("GET /api/settings/claude", client.get("/api/settings/claude"))
    op = "PUT /api/settings/claude"
    snapshots.pin(op, client.put("/api/settings/claude", json={"mode": "subscription"}))
    snapshots.pin(op, client.put("/api/settings/claude", json={"mode": "gateway", "baseUrl": "http://example.com"}), variant="placeholder base url")


def test_claude_connection_test(client, snapshots, monkeypatch) -> None:
    monkeypatch.setattr("cbc.modules.ops.api.claude_cli.preflight", lambda *args, **kwargs: None)
    snapshots.pin("POST /api/settings/claude/test", client.post("/api/settings/claude/test"))


def test_ollama_models_rejects_a_disallowed_host(client, snapshots) -> None:
    response = client.get("/api/settings/ollama/models", params={"baseUrl": "ftp://models.internal"})
    snapshots.pin("GET /api/settings/ollama/models", response, variant="non-http base url")
    assert response.status_code == 400


def test_oauth_start(client, snapshots, monkeypatch) -> None:
    op = "POST /api/settings/claude/oauth/start"
    monkeypatch.setitem(sys.modules, "pty", types.ModuleType("pty"))
    monkeypatch.setattr("shutil.which", lambda name: None)
    snapshots.pin(op, client.post("/api/settings/claude/oauth/start"), variant="no claude cli")
    monkeypatch.setenv("APP_ENV", "production")
    snapshots.pin(op, client.post("/api/settings/claude/oauth/start"), variant="production")


def test_oauth_code_for_an_unknown_session(client, snapshots) -> None:
    body = {"session": "no-such-session", "code": "abc"}
    snapshots.pin("POST /api/settings/claude/oauth/code", client.post("/api/settings/claude/oauth/code", json=body), variant="unknown session")


# ── integrations, autopilot, ops, audit ──────────────────────────────────────


def test_integrations(client, snapshots) -> None:
    snapshots.pin("GET /api/integrations", client.get("/api/integrations"))


def test_autopilot(client, state, snapshots) -> None:
    op = "POST /api/projects/{code}/orchestrate/autopilot"
    url = f"/api/projects/{state['code']}/orchestrate/autopilot"
    snapshots.pin(op, client.post(url))
    snapshots.pin(op, client.post(url), variant="already running")
    finish_pipeline_jobs(TEST_DB, state["code"])


def test_ops_spend(client, snapshots) -> None:
    snapshots.pin("GET /api/ops/spend", client.get("/api/ops/spend", params={"hours": 24}))


def test_audit_log(client, snapshots) -> None:
    snapshots.pin("GET /api/audit", client.get("/api/audit", params={"limit": 5}))


def test_delete_a_project(client, state, snapshots) -> None:
    op = "DELETE /api/projects/{code}"
    snapshots.pin(op, client.delete(f"/api/projects/{state['code']}"))
    snapshots.pin(op, client.delete(f"/api/projects/{state['code']}"), variant="already deleted")


def test_parsing_settings(client, snapshots) -> None:
    """The MinerU parser's runtime knobs. `PARSER_URL` empty means parsing is off."""
    snapshots.pin("GET /api/settings/parsing", client.get("/api/settings/parsing"))
    op = "PUT /api/settings/parsing"
    snapshots.pin(op, client.put("/api/settings/parsing", json={"profile": "medium"}))
    snapshots.pin(
        op,
        client.put("/api/settings/parsing", json={"profile": "not-a-profile"}),
        variant="unknown profile",
    )


def test_parsing_connection_test(client, snapshots) -> None:
    """With no parser configured this must answer, not hang or 500."""
    snapshots.pin("POST /api/settings/parsing/test", client.post("/api/settings/parsing/test"))
