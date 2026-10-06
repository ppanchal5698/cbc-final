"""Every margin override carries a reason code (requirements 5.1, 7.4).

Given with the margin, or chosen afterwards for a margin already overridden. The
estimator's own words, when they give some, are kept beside the code.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_override_reasons"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def line(client):
    code = client.post("/api/projects", json={"name": "Override reasons bid", "state": "IN"}).json()["code"]
    created = client.post(f"/api/projects/{code}/quote/lines",
                          json={"description": "LOCKSET", "division": "08 71 00", "qty": 1, "cost": 74.0})
    return code, created.json()["line"]["id"]


def _patch(client, line, body) -> dict:
    code, line_id = line
    response = client.patch(f"/api/projects/{code}/quote/lines/{line_id}", json=body)
    assert response.status_code == 200, response.text
    return response.json()["line"]


def test_a_margin_override_carries_its_reason_code(client, line):
    updated = _patch(client, line, {"margin": 0.30, "overrideCode": "competitive"})
    assert (updated["marginOverridden"], updated["overrideCode"], updated["overrideReason"]) == (
        True, "competitive", "Competitive bid")
    assert updated["overrides"][-1]["code"] == "competitive"


def test_a_reason_chosen_afterwards_keeps_the_estimators_words(client, line):
    updated = _patch(client, line, {"margin": 0.32})
    assert updated["overrideCode"] is None and updated["overrideReason"] is None

    coded = _patch(client, line, {"overrideCode": "distributor_buy"})
    assert (coded["overrideCode"], coded["overrideReason"], coded["margin"]) == ("distributor_buy", "Distributor buy", 0.32)

    worded = _patch(client, line, {"overrideCode": "special_customer", "overrideReason": "Wendy's program margin"})
    assert (worded["overrideCode"], worded["overrideReason"]) == ("special_customer", "Wendy's program margin")


def test_an_unknown_reason_code_is_refused(client, line):
    code, line_id = line
    response = client.patch(f"/api/projects/{code}/quote/lines/{line_id}", json={"overrideCode": "because"})
    assert response.status_code == 422
