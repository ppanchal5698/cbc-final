"""A GET must not change the database.

The quote and proposal screens used to re-price and re-store the whole bid on
every read - on every page load, and again on every four-second poll while a job
ran. That made the hottest read path the heaviest write path, made the responses
uncacheable and unsafe to retry, and let a PATCH landing between another
request's read and its write be silently reverted.
"""
from __future__ import annotations

import pytest

from cbc.config import settings
from tests.shared import ROOT, opshub_client

TEST_DB = "cbc_opshub_test_reads"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def project(client):
    created = client.post(
        "/api/projects",
        json={"name": "Read only reads", "state": "OH", "gc": "Cortlandt Builders LLC"},
    )
    assert created.status_code == 201
    code = created.json()["code"]

    for part, cost in (("150CX18", 74.33), ("B-2888", 42.10)):
        assert (
            client.post(
                f"/api/projects/{code}/quote/lines",
                json={"part": part, "description": part, "division": "08 71 00",
                      "qty": 2, "cost": cost, "margin": 0.27},
            ).status_code
            == 201
        )
    return code


def _snapshot(database) -> dict:
    """Everything a re-price would touch, as it currently stands."""
    return {
        "lines": sorted(
            (
                str(row["_id"]),
                row.get("sell"),
                row.get("extended"),
                row.get("margin"),
                str(row.get("marginCheck")),
            )
            for row in database["quoteLines"].find({})
        ),
        "quotes": [
            {k: str(v) for k, v in row.items() if k != "_id"}
            for row in database["quotes"].find({})
        ],
    }


@pytest.fixture()
def database():
    from pymongo import MongoClient

    client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        yield client[TEST_DB]
    finally:
        client.close()


def test_reading_the_quote_changes_nothing(client, project, database) -> None:
    # First read may legitimately settle stored values written by another route.
    client.get(f"/api/projects/{project}/quote")
    before = _snapshot(database)

    for _ in range(3):
        response = client.get(f"/api/projects/{project}/quote")
        assert response.status_code == 200

    assert _snapshot(database) == before, "a GET on the quote wrote to the database"


def test_reading_the_quote_still_returns_correct_totals(client, project) -> None:
    """Computing instead of storing must not change the numbers."""
    body = client.get(f"/api/projects/{project}/quote").json()

    # 74.33 and 42.10 at 27%, two of each, plus Ohio tax at 8%.
    assert body["totals"]["subtotal"] == pytest.approx(319.00, abs=0.02)
    assert body["totals"]["taxJurisdiction"] == "OH"
    assert body["totals"]["tax"] == pytest.approx(25.52, abs=0.02)
    assert body["lineCount"] == 2
    for group in body["groups"]:
        for line in group["lines"]:
            assert line["sell"] is not None, "lines are priced in the response"


def test_reading_the_proposal_changes_nothing(client, project, database) -> None:
    client.get(f"/api/projects/{project}/proposal")
    before = _snapshot(database)

    assert client.get(f"/api/projects/{project}/proposal").status_code == 200
    assert client.get(f"/api/projects/{project}/proposal/render").status_code == 200

    assert _snapshot(database) == before, "a GET on the proposal wrote to the database"


def test_editing_a_line_does_persist(client, project, database) -> None:
    """The write has to happen somewhere - it moved to the routes that change things."""
    line_id = str(database["quoteLines"].find_one({"part": "150CX18"})["_id"])

    updated = client.patch(
        f"/api/projects/{project}/quote/lines/{line_id}",
        json={"cost": 100.0, "overrideReason": "distributor buy"},
    )
    assert updated.status_code == 200

    stored = database["quoteLines"].find_one({"part": "150CX18"})
    assert stored["cost"] == 100.0
    assert stored["sell"] == pytest.approx(136.99, abs=0.02), "re-priced and stored"
    assert database["quotes"].find_one({})["grandTotal"] == pytest.approx(
        updated.json()["totals"]["grandTotal"]
    )


def test_an_unpriceable_line_does_not_break_the_screen(client, project, database) -> None:
    """A cost that predates the schema bounds still has to render (CBC-017)."""
    database["quoteLines"].update_one({"part": "B-2888"}, {"$set": {"cost": -5.0}})

    body = client.get(f"/api/projects/{project}/quote")
    assert body.status_code == 200, "one bad line took the whole quote down"

    lines = [line for group in body.json()["groups"] for line in group["lines"]]
    broken = next(line for line in lines if line["part"] == "B-2888")
    assert broken["sell"] is None
    assert "negative" in (broken.get("priceError") or ""), "and it says why"

    assert client.get(f"/api/projects/{project}/proposal").status_code == 200
