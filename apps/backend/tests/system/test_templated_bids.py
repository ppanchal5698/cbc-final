"""A templated bid starts as a copy of a prior job's quote (FR-1d, FR-11).

The estimators' word for it is "Save As from a prior job", and the risk the
requirement names is the rows left over from that job. So every copied line is
marked, the proposal waits on each until an estimator keeps it, and the prior
bid is never touched.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_templated"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


def _bid(client, name: str, **fields) -> dict:
    response = client.post("/api/projects", json={"name": name, "state": "OH", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def _line(client, code: str, description: str, cost: float) -> dict:
    response = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": description, "division": "08 71 00", "qty": 2, "cost": cost, "margin": 0.27},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["line"]


def _lines(client, code: str) -> list[dict]:
    quote = client.get(f"/api/projects/{code}/quote").json()
    return [line for group in quote["groups"] for line in group["lines"]]


def _carried(line: dict) -> bool:
    return "carried_from_prior" in line["flags"]


@pytest.fixture(scope="module")
def priors(client):
    prior = _bid(client, "Dutch Bros prototype", brand="Dutch Bros")
    _line(client, prior["code"], "Hager 3500 lockset", 74.0)
    _line(client, prior["code"], "Hager 5100 closer", 61.5)
    other = _bid(client, "Wendy's remodel", brand="Wendy's")
    _line(client, other["code"], "Bobrick grab bar", 38.0)
    return {"prior": prior["code"], "other": other["code"]}


def test_starting_from_a_prior_copies_its_lines_marked(client, priors):
    bid = _bid(client, "Dutch Bros store 41", brand="Dutch Bros")
    assert priors["prior"] in {p["code"] for p in client.get(f"/api/projects/{bid['code']}/prior-quotes").json()["priors"]}

    assert client.post(f"/api/projects/{bid['code']}/reuse/{priors['prior']}").status_code == 200

    lines = _lines(client, bid["code"])
    assert sorted(line["description"] for line in lines) == ["Hager 3500 lockset", "Hager 5100 closer"]
    assert all(_carried(line) and line["carriedFrom"] == priors["prior"] for line in lines)
    assert {line["cost"] for line in lines} == {74.0, 61.5}
    assert client.get(f"/api/projects/{bid['code']}").json()["templateSourceCode"] == priors["prior"]

    # The prior job is read, never written.
    assert not any(_carried(line) for line in _lines(client, priors["prior"]))


def test_a_carried_line_holds_the_proposal_until_it_is_kept(client, priors):
    bid = _bid(client, "Dutch Bros store 42", brand="Dutch Bros")
    client.post(f"/api/projects/{bid['code']}/reuse/{priors['prior']}")

    held = client.get(f"/api/projects/{bid['code']}/proposal").json()["readiness"]
    assert [f["field"] for f in held["blockingFlags"]].count("carried") == 2

    # Editing a line is looking at it; the other is still waiting.
    first, second = _lines(client, bid["code"])
    client.patch(f"/api/projects/{bid['code']}/quote/lines/{first['id']}", json={"qty": 3})
    assert [_carried(line) for line in _lines(client, bid["code"])].count(True) == 1

    kept = client.post(f"/api/projects/{bid['code']}/quote/carried/keep")
    assert kept.json() == {"kept": 1}
    readiness = client.get(f"/api/projects/{bid['code']}/proposal").json()["readiness"]
    assert "carried" not in [f["field"] for f in readiness["blockingFlags"]]


def test_a_different_prior_replaces_only_lines_nobody_kept(client, priors):
    bid = _bid(client, "Dutch Bros store 43", brand="Dutch Bros")
    client.post(f"/api/projects/{bid['code']}/reuse/{priors['prior']}")
    client.post(f"/api/projects/{bid['code']}/reuse/{priors['other']}")
    assert [line["description"] for line in _lines(client, bid["code"])] == ["Bobrick grab bar"]

    client.post(f"/api/projects/{bid['code']}/quote/carried/keep")
    refused = client.post(f"/api/projects/{bid['code']}/reuse/{priors['prior']}")
    assert refused.status_code == 409
    assert "of its own" in refused.json()["detail"]
    assert client.get(f"/api/projects/{bid['code']}").json()["templateSourceCode"] == priors["other"]


def test_a_templated_bid_starts_from_the_newest_matching_job(client):
    older = _bid(client, "Culver's 1", brand="Culver's")
    _line(client, older["code"], "From the older job", 10.0)
    newer = _bid(client, "Culver's 2", brand="Culver's")
    _line(client, newer["code"], "From the newer job", 12.0)

    bid = _bid(client, "Culver's 3", brand="Culver's", mode="templated")

    assert bid["templateSourceCode"] == newer["code"]
    lines = _lines(client, bid["code"])
    assert [line["description"] for line in lines] == ["From the newer job"]
    assert all(_carried(line) and line["carriedFrom"] == newer["code"] for line in lines)


def test_a_carried_cost_is_as_old_as_the_prior_jobs(client, priors):
    """FR-6a: a cost typed on the prior job two years ago is two years old on this
    one too - the copy made today does not make it fresh."""
    from datetime import datetime, timedelta, timezone

    from bson import ObjectId

    from cbc.shared.persistence import names
    from tests.shared import mongo_client

    old = _bid(client, "Wendy's 2024 refresh", brand="Wendy's")
    _line(client, old["code"], "Gamco grab bar", 31.0)
    raw = mongo_client()
    try:
        two_years = datetime.now(timezone.utc) - timedelta(days=730)
        raw[TEST_DB][names.ESTIMATE_LINES].update_many({"projectId": ObjectId(old["id"])},
                                                       {"$set": {"createdAt": two_years}})
    finally:
        raw.close()
    bid = _bid(client, "Wendy's 2026 refresh", brand="Wendy's")
    client.post(f"/api/projects/{bid['code']}/reuse/{old['code']}")
    [line] = _lines(client, bid["code"])
    assert line["freshness"]["asOf"] == two_years.date().isoformat()
    assert line["freshness"]["status"] not in ("fresh", "aging")
