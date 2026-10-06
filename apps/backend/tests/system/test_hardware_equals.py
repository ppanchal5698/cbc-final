"""The equal CBC quotes for an Allegion part (FR-17), kept as estimators name it (FR-13).

Allegion is bought only through a distributor, so a bid that specifies it is
quoted with a Hager equal as the base line. Naming that equal on a quote keeps
it, and the next bid that specifies the part prices it.
"""
from __future__ import annotations

import pytest
from bson import ObjectId

from cbc.modules.pricing.api import reference_store
from cbc.shared.persistence import names
from tests.shared import TEST_ACTOR, mongo_client, opshub_client

TEST_DB = "cbc_opshub_test_hardware_equals"
URL = "/api/reference/hardware-equals"


@pytest.fixture(scope="module")
def client():
    reference_store.invalidate()
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client
    reference_store.invalidate()


def test_naming_the_equal_on_a_quote_keeps_it_for_the_next_bid(client) -> None:
    bid = client.post("/api/projects", json={"name": "Equals bid", "state": "OH"}).json()
    raw = mongo_client()
    try:
        lines = raw[TEST_DB][names.ESTIMATE_LINES]
        base_id = lines.insert_one({
            "projectId": ObjectId(bid["id"]), "lineKey": "1:03", "description": "Hager equal to Von Duprin 99EO",
            "manufacturer": "Hager", "division": "08 71 00", "group": "01", "qty": 1, "margin": 0.27,
            "flags": ["allegion_equal_needed"], "deductedBy": ["Allegion as specified"],
        }).inserted_id
        lines.insert_one({
            "projectId": ObjectId(bid["id"]), "lineKey": "1:03:allegion", "part": "99EO", "manufacturer": "Von Duprin",
            "description": "EXIT DEVICE", "division": "08 71 00", "group": "01", "qty": 1,
            "alternateGroup": "Allegion as specified", "costSource": "DISTRIBUTOR_MANUAL", "flags": [],
        })
    finally:
        raw.close()

    edited = client.patch(f"/api/projects/{bid['code']}/quote/lines/{base_id}", json={"part": "4500"})
    assert edited.status_code == 200 and "allegion_equal_needed" not in edited.json()["line"]["flags"]
    [kept] = [row for row in client.get(URL).json()["rows"] if row["part"] == "99EO"]
    assert (kept["brand"], kept["equal_manufacturer"], kept["equal_part"], kept["named_by"]) == (
        "Von Duprin", "Hager", "4500", TEST_ACTOR)


def test_settings_add_and_remove_an_equal(client) -> None:
    added = client.patch(URL, json={"items": [{"brand": "LCN", "part": "4040XP", "equal_part": "5100"}]})
    assert added.status_code == 200
    assert any(row["part"] == "4040XP" and row["named_by"] == TEST_ACTOR for row in added.json()["rows"])
    removed = client.patch(URL, json={"remove": ["4040XP"]}).json()
    assert not any(row["part"] == "4040XP" for row in removed["rows"])
    assert client.patch(URL, json={"items": [{"part": "L9080", "equal_part": " "}]}).status_code == 422
