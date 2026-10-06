"""Revisions and re-issue (FR-14, requirements 6.4).

A version records the drawings, specs and addenda behind it. A proposal issued
before an addendum or a new version prints as the next revision - a draft until
it is approved again - and says which issue it supersedes. Routing the same
proposal to someone else is not a new revision.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_revisions"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def code(client) -> str:
    bid = client.post("/api/projects", json={"name": "Revisions bid", "state": "IN", "initiator": "Matt"}).json()
    line = client.post(f"/api/projects/{bid['code']}/quote/lines", json={
        "description": "LOCKSET", "division": "08 71 00", "qty": 1, "cost": 74.0, "margin": 0.27,
    })
    assert line.status_code in (200, 201), line.text
    return bid["code"]


def _proposal(client, code) -> dict:
    return client.get(f"/api/projects/{code}/proposal").json()


def _approve(client, code) -> None:
    response = client.post(f"/api/projects/{code}/proposal/complete", json={})
    assert response.status_code == 200, response.text


def test_the_first_issue_is_the_original(client, code):
    _approve(client, code)
    proposal = _proposal(client, code)["proposal"]
    number = f"Q-{code.split('-')[-1]}"
    assert (proposal["proposalNo"], proposal["draft"], proposal["supersedes"]) == (number, False, None)

    _approve(client, code)  # routed again, unchanged: the same issue
    assert _proposal(client, code)["proposal"]["proposalNo"] == number


def test_an_addendum_after_the_issue_makes_the_next_revision_a_draft(client, code):
    number = f"Q-{code.split('-')[-1]}"
    client.post(f"/api/projects/{code}/addenda", json={"issuedOn": "2026-10-05", "changedDocuments": "A601"})

    payload = _proposal(client, code)
    proposal = payload["proposal"]
    assert (proposal["proposalNo"], proposal["revision"], proposal["draft"]) == (f"{number} R1", 1, True)
    assert proposal["supersedes"]["proposalNo"] == number
    assert "this is revision 1, a draft until it is approved again" in payload["readiness"]["note"]

    html = client.get(f"/api/projects/{code}/proposal/render").text
    assert f"{number} R1" in html and f"Supersedes</td><td>{number} issued" in html


def test_approving_the_revision_issues_it_and_supersedes_the_original(client, code):
    number = f"Q-{code.split('-')[-1]}"
    _approve(client, code)
    proposal = _proposal(client, code)["proposal"]
    assert (proposal["proposalNo"], proposal["draft"]) == (f"{number} R1", False)
    assert proposal["supersedes"]["proposalNo"] == number


def test_a_version_records_what_it_was_based_on(client, code):
    created = client.post(f"/api/projects/{code}/versions", json={"reason": "Addendum 1 reviewed"})
    assert created.status_code == 201, created.text
    [latest, *_] = client.get(f"/api/projects/{code}/versions").json()["versions"]
    assert latest["basis"]["addenda"] == [1] and latest["basis"]["documents"] == []

    # A new version after the issue is a change under it, like an addendum.
    assert _proposal(client, code)["proposal"]["proposalNo"].endswith(" R2")
