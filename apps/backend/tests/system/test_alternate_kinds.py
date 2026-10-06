"""Additive, deductive and substitution alternates through the API (FR-14).

The base bid counts a deductive alternate's lines - it is base scope the
alternate offers to delete - and a substitution is offered instead of the base
lines that name it. The quote's total, the alternates list and the proposal all
read the same rule.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_alternate_kinds"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def bid(client):
    code = client.post("/api/projects", json={"name": "Alternate kinds bid", "state": "IN"}).json()["code"]
    lines = {}
    for name, cost in (("LOCKSET", 100.0), ("AUTO OPERATOR", 50.0), ("HAGER EQUAL CLOSER", 80.0),
                       ("LCN CLOSER AS SPECIFIED", 120.0)):
        lines[name] = client.post(f"/api/projects/{code}/quote/lines", json={
            "description": name, "division": "08 71 00", "qty": 1, "cost": cost, "margin": 0.0,
        }).json()["line"]["id"]
    return code, lines


def _subtotal(client, code) -> float:
    return client.get(f"/api/projects/{code}/quote").json()["totals"]["subtotal"]


def _assign(client, code, ids, alternate, **extra):
    response = client.post(f"/api/projects/{code}/alternates/assign",
                           json={"ids": ids, "alternate": alternate, "scope": "quote-lines", **extra})
    assert response.status_code == 200, response.text


def test_each_kind_moves_the_base_and_its_combination(client, bid):
    code, lines = bid
    assert _subtotal(client, code) == 350.0

    assert client.post(f"/api/projects/{code}/alternates",
                       json={"name": "Alt 2", "kind": "substitution", "description": "LCN closers as specified"}
                       ).status_code == 201
    _assign(client, code, [lines["LCN CLOSER AS SPECIFIED"]], "Alt 2")
    _assign(client, code, [lines["HAGER EQUAL CLOSER"]], "Alt 2", role="replaced")
    assert _subtotal(client, code) == 230.0  # the substitute is offered, not in the bid

    assert client.post(f"/api/projects/{code}/alternates",
                       json={"name": "Alt 1", "kind": "deductive"}).status_code == 201
    _assign(client, code, [lines["AUTO OPERATOR"]], "Alt 1")
    assert _subtotal(client, code) == 230.0  # base scope the alternate offers to delete

    listed = client.get(f"/api/projects/{code}/alternates").json()
    groups = {group["label"]: group for group in listed["alternates"]}
    assert [group["label"] for group in listed["alternates"]] == ["Base bid", "Alt 1", "Alt 2"]
    assert (groups["Alt 1"]["kind"], groups["Alt 1"]["net"], groups["Alt 1"]["withBase"]) == ("deductive", -50.0, 180.0)
    assert (groups["Alt 2"]["net"], groups["Alt 2"]["withBase"]) == (40.0, 270.0)  # +120 - 80
    assert [c["total"] for c in listed["cumulative"]] == [180.0, 220.0]
    assert listed["overlaps"] == []

    html = client.get(f"/api/projects/{code}/proposal/render").text
    assert "Alt 1 &mdash; deduct alternate" in html and "Deduct $50.00" in html
    assert "Offered instead of: HAGER EQUAL CLOSER." in html and "Add $40.00" in html
    assert "Base bid with Alt 1 + Alt 2" in html


def test_changing_an_alternates_kind_moves_the_base(client, bid):
    code, _ = bid
    changed = client.patch(f"/api/projects/{code}/alternates/Alt 1", json={"kind": "additive", "priority": 2})
    assert changed.status_code == 200 and changed.json()["kind"] == "additive"
    assert _subtotal(client, code) == 180.0  # the operator is now offered as an add, not in the bid
    assert [g["label"] for g in client.get(f"/api/projects/{code}/alternates").json()["alternates"]][1] == "Alt 2"

    assert client.patch(f"/api/projects/{code}/alternates/No such", json={"kind": "deductive"}).status_code == 404


def test_a_replaced_line_keeps_its_replacement_through_a_reprice(client, bid):
    """Recorded as an edit, so the next pricing pass does not undo it."""
    code, lines = bid
    quote = client.get(f"/api/projects/{code}/quote").json()
    closer = next(line for group in quote["groups"] for line in group["lines"] if line["id"] == lines["HAGER EQUAL CLOSER"])
    assert closer["deductedBy"] == ["Alt 2"]
    assert closer["overrides"][-1]["after"] == {"deductedBy": "Alt 2"}
