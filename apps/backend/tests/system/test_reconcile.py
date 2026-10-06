"""Reconciling a version line by line (FR-14, requirements 6.4).

Every door and quote line added, removed or changed since the version was frozen
is a difference. The estimator keeps it, or reverts it - a changed field back to
the version's value, an addition taken out, a removal restored. When none is left
undecided, the version is reconciled.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_reconcile"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def bid(client):
    code = client.post("/api/projects", json={"name": "Reconcile bid", "state": "IN"}).json()["code"]
    doors = {mark: client.post(f"/api/projects/{code}/line-items",
                               json={"mark": mark, "description": "Door", "division": "08 11 00", "qty": 1}).json()["id"]
             for mark in ("D1", "D2")}
    lines = {name: client.post(f"/api/projects/{code}/quote/lines",
                               json={"description": name, "division": "08 71 00", "qty": 2, "cost": 10.0, "margin": 0.27}
                               ).json()["line"]["id"]
             for name in ("HINGE", "CLOSER")}
    assert client.post(f"/api/projects/{code}/versions", json={"reason": "Addendum 1"}).status_code == 201

    # What the addendum did to the bid.
    client.patch(f"/api/projects/{code}/line-items/{doors['D1']}", json={"qty": 2})
    client.delete(f"/api/projects/{code}/line-items/{doors['D2']}")
    client.post(f"/api/projects/{code}/line-items", json={"mark": "D3", "description": "Door", "division": "08 11 00", "qty": 1})
    client.patch(f"/api/projects/{code}/quote/lines/{lines['HINGE']}", json={"qty": 4})
    client.delete(f"/api/projects/{code}/quote/lines/{lines['CLOSER']}")
    client.post(f"/api/projects/{code}/quote/lines", json={"description": "KICK PLATE", "division": "08 71 00", "qty": 1, "cost": 5.0})
    return code


def _diff(client, code) -> dict:
    return client.get(f"/api/projects/{code}/versions/1/diff").json()


def _decide(client, code, row, decision) -> dict:
    response = client.post(f"/api/projects/{code}/versions/1/decisions",
                           json={"kind": row["kind"], "key": row["key"], "decision": decision})
    assert response.status_code == 200, response.text
    return response.json()


def _row(diff, kind, label) -> dict:
    return next(r for r in diff["rows"] if r["kind"] == kind and r["label"] == label)


def test_every_difference_is_a_row_doors_and_quote_lines(client, bid):
    diff = _diff(client, bid)
    found = {(r["kind"], r["label"], r["change"]) for r in diff["rows"]}
    assert found == {("opening", "D1", "changed"), ("opening", "D2", "removed"), ("opening", "D3", "added"),
                     ("line", "HINGE", "changed"), ("line", "CLOSER", "removed"), ("line", "KICK PLATE", "added")}
    assert diff["undecided"] == 6 and diff["added"] == ["D3"] and diff["removed"] == ["D2"]


def test_each_difference_is_kept_or_reverted_and_the_version_reconciles(client, bid):
    code = bid
    diff = _diff(client, code)
    _decide(client, code, _row(diff, "opening", "D1"), "keep")
    _decide(client, code, _row(diff, "opening", "D3"), "revert")   # the addition taken out
    _decide(client, code, _row(diff, "opening", "D2"), "revert")   # the removal undone
    _decide(client, code, _row(diff, "line", "HINGE"), "revert")   # back to qty 2
    _decide(client, code, _row(diff, "line", "KICK PLATE"), "keep")
    last = _decide(client, code, _row(diff, "line", "CLOSER"), "revert")
    assert (last["undecided"], last["reconciled"]) == (0, True)

    marks = {row["mark"]: row for row in client.get(f"/api/projects/{code}/line-items").json()["lineItems"]}
    assert set(marks) == {"D1", "D2"} and marks["D1"]["qty"] == 2
    quote = client.get(f"/api/projects/{code}/quote").json()
    lines = {line["description"]: line for group in quote["groups"] for line in group["lines"]}
    assert set(lines) == {"HINGE", "CLOSER", "KICK PLATE"} and lines["HINGE"]["qty"] == 2
    assert lines["HINGE"]["overrides"][-1]["reason"] == "reverted to version 1"

    listed = client.get(f"/api/projects/{code}/versions").json()["versions"][0]
    assert listed["reconciled"] is True


def test_a_difference_that_is_not_there_is_refused(client, bid):
    response = client.post(f"/api/projects/{bid}/versions/1/decisions",
                           json={"kind": "line", "key": "nothing", "decision": "keep"})
    assert response.status_code == 404
