"""A list adder the legend names, added by the estimator (NR-4).

An adder is a list value: it goes on the list price and the line's own multiplier
applies to the sum. Adding one is the estimator's act, recorded on the line.
"""
from __future__ import annotations

import pytest
from bson import ObjectId

from cbc.shared.persistence import names
from tests.shared import mongo_client, opshub_client

TEST_DB = "cbc_opshub_test_adders"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


def _line(client, **fields) -> tuple[str, str]:
    bid = client.post("/api/projects", json={"name": "Adders bid", "state": "OH"}).json()
    raw = mongo_client()
    try:
        line_id = raw[TEST_DB][names.ESTIMATE_LINES].insert_one({
            "projectId": ObjectId(bid["id"]), "lineKey": "1:01:3580", "description": "LOCKSET 3580 LEAD LINED SFIC",
            "division": "08 71 00", "group": "01", "qty": 1, "margin": 0.27, "addedByHand": False,
            "flags": ["adder_named"], **fields,
        }).inserted_id
    finally:
        raw.close()
    return bid["code"], str(line_id)


PRICED = {
    "cost": 74.33, "listPrice": 256.31, "multiplier": 0.29, "costSource": "LIST_X_MULTIPLIER",
    "costSourceDetail": "hager_price_book_18.pdf p.297 3580 list $256.31 x 0.29",
    "adderCandidates": [{"name": "Lead lined", "listAdder": 214.25}, {"name": "SFIC core", "listAdder": 69.95}],
}


def test_an_adder_goes_on_the_list_and_takes_the_lines_multiplier(client):
    code, line_id = _line(client, **PRICED)

    first = client.post(f"/api/projects/{code}/quote/lines/{line_id}/adders/0").json()["line"]
    assert first["cost"] == 136.46  # (256.31 + 214.25) x 0.29
    assert first["costSourceDetail"].endswith("+ Lead lined list adder $214.25")
    assert [a["name"] for a in first["adderCandidates"]] == ["SFIC core"] and "adder_named" in first["flags"]

    second = client.post(f"/api/projects/{code}/quote/lines/{line_id}/adders/0").json()["line"]
    assert second["cost"] == 156.75  # (256.31 + 214.25 + 69.95) x 0.29
    assert second["adderCandidates"] == [] and "adder_named" not in second["flags"]
    assert second["overrides"][-1]["reason"] == "added the SFIC core list adder"


def test_an_adder_needs_a_list_price_to_go_on(client):
    code, line_id = _line(client, cost=80.0, costSource="P21_LAST_PO",
                          adderCandidates=[{"name": "Lead lined", "listAdder": 214.25}])
    refused = client.post(f"/api/projects/{code}/quote/lines/{line_id}/adders/0")
    assert refused.status_code == 409 and "by hand" in refused.json()["detail"]
    assert client.post(f"/api/projects/{code}/quote/lines/{line_id}/adders/3").status_code == 404
