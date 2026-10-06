"""An undecided line offers its close matches, and an estimator chooses one (FR-8).

The choice is an estimator's edit like any other: the part, its cost and where
that cost came from move together, the line stops waiting on a pick, and a
re-price leaves it as they chose it.
"""
from __future__ import annotations

import pytest
from bson import ObjectId

from cbc.shared.persistence import names
from tests.shared import mongo_client, opshub_client

TEST_DB = "cbc_opshub_test_close_matches"

MATCHES = [
    {"label": "Hager 5100 ALM, list $440.71", "part": "5100", "manufacturer": "Hager", "cost": 132.21,
     "costSource": "LIST_X_MULTIPLIER", "costSourceDetail": "hager_price_book_18.pdf p.297 list $440.71 x 0.30",
     "listPrice": 440.71, "multiplier": 0.3, "multiplierTier": "door_controls",
     "multiplierEffectiveDate": "2026-02-02", "priceBookVersion": "Hager Price Book #18, effective 2026-02-02"},
    {"label": "Hager 5100 ALM PA, list $512.00", "part": "5100-PA", "manufacturer": "Hager", "cost": 153.6,
     "costSource": "LIST_X_MULTIPLIER", "costSourceDetail": "hager_price_book_18.pdf p.297 list $512.00 x 0.30",
     "listPrice": 512.0, "multiplier": 0.3, "multiplierTier": "door_controls",
     "multiplierEffectiveDate": "2026-02-02", "priceBookVersion": "Hager Price Book #18, effective 2026-02-02"},
]


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def undecided(client):
    bid = client.post("/api/projects", json={"name": "Close matches bid", "state": "OH"}).json()
    raw = mongo_client()
    try:
        line_id = raw[TEST_DB][names.ESTIMATE_LINES].insert_one({
            "projectId": ObjectId(bid["id"]), "lineKey": "1:01:5100", "description": "CLOSER 5100 ALM",
            "division": "08 71 00", "group": "01", "qty": 2, "cost": None, "margin": None,
            "costSource": "MANUAL", "priceStatus": "NEEDS_JUDGMENT", "addedByHand": False,
            "flags": ["ambiguous_match"], "closeMatches": MATCHES,
        }).inserted_id
    finally:
        raw.close()
    return bid["code"], str(line_id)


def test_choosing_a_close_match_prices_the_line_from_it(client, undecided):
    code, line_id = undecided
    response = client.post(f"/api/projects/{code}/quote/lines/{line_id}/close-matches/1")
    assert response.status_code == 200, response.text

    line = response.json()["line"]
    assert (line["part"], line["cost"], line["listPrice"]) == ("5100-PA", 153.6, 512.0)
    assert line["priceBookVersion"].startswith("Hager Price Book #18")
    assert "ambiguous_match" not in line["flags"] and line["priceStatus"] == "PRICED"
    assert line["overrides"][-1]["reason"] == "chose a close match: Hager 5100 ALM PA, list $512.00"
    assert response.json()["totals"]["unpricedLines"] == 0


def test_a_close_match_the_line_does_not_have_is_refused(client, undecided):
    code, line_id = undecided
    assert client.post(f"/api/projects/{code}/quote/lines/{line_id}/close-matches/7").status_code == 404
