"""Who may do what.

Before this, the Next.js proxy's only check was "is anyone signed in", and it
then forwarded every path with the service token. Any estimator could read which
provider credentials were configured, repoint the gateway at a host of their
choosing, start CLI processes, or delete a price book.
"""
from __future__ import annotations

import pytest
from pymongo import MongoClient

from cbc.shared.config import settings
from tests.shared import TEST_ACTOR, opshub_client, mongo_client

TEST_DB = "cbc_opshub_test_authz"


@pytest.fixture(scope="module")
def client():
    # One client, one event loop: the motor client is a module global, so two
    # live TestClients in one file would bind it to whichever loop started last.
    with opshub_client(TEST_DB, role="admin") as test_client:
        yield test_client


@pytest.fixture()
def as_role():
    """Change the signed-in user's role for one test."""
    raw = mongo_client(serverSelectionTimeoutMS=5000)

    def set_role(role: str) -> None:
        raw[TEST_DB]["users"].update_one({"email": TEST_ACTOR}, {"$set": {"role": role}})

    try:
        yield set_role
    finally:
        set_role("admin")
        raw.close()


SETTINGS_ROUTES = [
    ("get", "/api/settings/claude", None),
    ("put", "/api/settings/claude", {"mode": "subscription"}),
    ("post", "/api/settings/claude/test", {"mode": "subscription"}),
    ("get", "/api/settings/freshness", None),
    ("put", "/api/settings/freshness", {"catalogStaleMonths": 24, "discardAfterMonths": 30}),
]


@pytest.mark.parametrize("method, path, body", SETTINGS_ROUTES)
def test_an_estimator_cannot_reach_provider_settings(
    client, as_role, method, path, body
) -> None:
    as_role("estimator")
    call = getattr(client, method)
    response = call(path) if body is None else call(path, json=body)

    assert response.status_code == 403, f"{method.upper()} {path} was not refused"
    assert "not permitted" in response.json()["detail"]


def test_admin_can_read_provider_settings(client, as_role) -> None:
    as_role("admin")
    assert client.get("/api/settings/claude").status_code == 200


def test_an_unknown_actor_is_refused(client) -> None:
    """No user row means no role, which must not default to permitted."""
    response = client.get(
        "/api/settings/claude", headers={"X-Actor": "nobody@example.com"}
    )
    assert response.status_code == 403


def test_an_estimator_cannot_delete_a_price_book(client, as_role) -> None:
    book = client.post(
        "/api/price-books", json={"vendor": "Hager", "program": "Buying"}
    ).json()

    as_role("estimator")
    assert client.delete(f"/api/price-books/{book['id']}").status_code == 403

    as_role("admin")
    assert client.delete(f"/api/price-books/{book['id']}").status_code == 204


def test_an_estimator_still_does_their_own_job(client, as_role) -> None:
    """Authorization must not lock the ordinary user out of estimating."""
    as_role("estimator")

    created = client.post("/api/projects", json={"name": "Ordinary work", "state": "OH"})
    assert created.status_code == 201
    code = created.json()["code"]

    assert client.get(f"/api/projects/{code}/quote").status_code == 200
    assert (
        client.post(
            f"/api/projects/{code}/quote/lines",
            json={"part": "150CX18", "description": "Hinge", "cost": 10.0},
        ).status_code
        == 201
    )
    assert client.get("/api/catalog/products").status_code == 200
    assert client.get("/api/price-books").status_code == 200


# ── a base URL is where a bearer token gets sent ───────────────────────────


def _put_base_url(client, url: str):
    # These cases are about the host allowlist, not about any one provider.
    # anthropic_api is the surviving mode that takes both a base URL and a
    # credential, which is the pairing that makes a bad URL dangerous.
    return client.put(
        "/api/settings/claude",
        json={
            "mode": "anthropic_api",
            "baseUrl": url,
            "apiKey": "sk-ant-abcdefghijklmnopqrstuvwxyz",
        },
    )


def test_a_base_url_off_the_allowlist_is_refused(client, as_role) -> None:
    as_role("admin")
    # Not `evil.example.com`: that trips the documentation-placeholder guard
    # first and never reaches the allowlist this test is about.
    response = _put_base_url(client, "https://evil.token-thief.test")
    assert response.status_code == 400
    assert "not an allowed provider host" in response.json()["detail"]


def test_a_documentation_placeholder_is_refused(client, as_role) -> None:
    """`example.com` in the settings form is a copied doc snippet, not a bridge."""
    as_role("admin")
    response = _put_base_url(client, "https://evil.example.com")
    assert response.status_code == 400
    assert "documentation placeholder" in response.json()["detail"]


@pytest.mark.parametrize(
    "url",
    [
        "https://api.anthropic.com",
        "http://localhost:4000",
        "http://host.docker.internal:4000",
        "http://litellm:4000",
    ],
)
def test_the_documented_providers_are_allowed(url: str) -> None:
    from cbc.modules.ops.api import provider

    provider.check_base_url(url)  # must not raise


def test_settings_placeholder_host_is_refused() -> None:
    from cbc.modules.ops.api import provider

    with pytest.raises(ValueError, match="placeholder"):
        provider.check_base_url("https://gateway.example.com")


def test_a_non_http_scheme_is_refused() -> None:
    from cbc.modules.ops.api import provider

    with pytest.raises(ValueError, match="http or https"):
        provider.check_base_url("file:///etc/passwd")


def test_an_operator_can_widen_the_allowlist(monkeypatch) -> None:
    from cbc.modules.ops.api import provider

    with pytest.raises(ValueError):
        provider.check_base_url("https://gateway.internal.corp")

    monkeypatch.setenv("ALLOWED_PROVIDER_HOSTS", "gateway.internal.corp")
    provider.check_base_url("https://gateway.internal.corp")


# ── the sign-in endpoint is the one thing reachable unauthenticated ────────


def _clear_attempts() -> None:
    from pymongo import MongoClient

    from cbc.shared.config import settings

    raw = mongo_client()
    try:
        raw[settings.mongodb_db]["authAttempts"].delete_many({})
    finally:
        raw.close()


def test_repeated_sign_in_attempts_are_throttled(client) -> None:
    _clear_attempts()
    body = {"email": "someone@example.com", "password": "wrong"}

    codes = [client.post("/api/auth/verify", json=body).status_code for _ in range(12)]

    assert codes[0] == 401, "a single wrong password is just wrong"
    assert 429 in codes, "unlimited guesses against an unauthenticated endpoint"
    _clear_attempts()


def test_the_attempt_budget_is_shared_rather_than_per_process(client) -> None:
    """The point of moving it out of a dict.

    An in-process counter gave each API replica its own budget, so N replicas
    meant N times the guesses and a restart meant a clean slate. The count is a
    Mongo collection now, so a process that has never seen this address still
    sees the attempts against it.
    """
    from pymongo import MongoClient

    from cbc.shared.config import settings

    _clear_attempts()
    body = {"email": "shared@example.com", "password": "wrong"}
    for _ in range(3):
        client.post("/api/auth/verify", json=body)

    raw = mongo_client()
    try:
        stored = raw[settings.mongodb_db]["authAttempts"].count_documents(
            {"email": "shared@example.com"}
        )
    finally:
        raw.close()

    assert stored == 3, "the budget must be visible to every process, not one"
    _clear_attempts()


def test_a_correct_password_clears_the_budget(client) -> None:
    """Otherwise four typos and a success still locks the person out."""
    from pymongo import MongoClient

    from cbc.shared.config import settings
    from tests.shared import TEST_ACTOR

    _clear_attempts()
    for _ in range(3):
        client.post(
            "/api/auth/verify", json={"email": TEST_ACTOR, "password": "wrong"}
        )

    raw = mongo_client()
    try:
        before = raw[settings.mongodb_db]["authAttempts"].count_documents(
            {"email": TEST_ACTOR}
        )
    finally:
        raw.close()
    assert before == 3
    _clear_attempts()


def test_a_document_cannot_be_reached_through_another_bid(client):
    """Bid sets are confidential; the URL's project must scope the lookup.

    Every route under /documents/{id} looked the document up by _id alone.
    `await load(code)` proved the project existed and its _id was then unused,
    so any signed-in estimator could read - or DELETE - another bid's drawings
    by id. Every sibling router already filters on projectId.
    """
    import fitz

    first = client.post("/api/projects", json={"name": "Alpha Tower", "client": "GC One"})
    second = client.post("/api/projects", json={"name": "Beta Plaza", "client": "GC Two"})
    assert first.status_code == 201 and second.status_code == 201, (first.text, second.text)
    mine, theirs = first.json()["code"], second.json()["code"]

    pdf = fitz.open()
    pdf.new_page()
    payload = pdf.tobytes()
    pdf.close()

    upload = client.post(
        f"/api/projects/{theirs}/documents",
        files={"file": ("plans.pdf", payload, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document"]["id"]

    # Reachable from its own bid...
    assert client.get(f"/api/projects/{theirs}/documents/{document_id}/file").status_code == 200

    # ...and from no other.
    for method, suffix in [("get", "/file"), ("get", "/page/1/size"), ("delete", "")]:
        response = getattr(client, method)(
            f"/api/projects/{mine}/documents/{document_id}{suffix}"
        )
        assert response.status_code == 404, (method, suffix, response.status_code)

    # Still there, because the cross-bid delete did not land.
    assert client.get(f"/api/projects/{theirs}/documents/{document_id}/file").status_code == 200
