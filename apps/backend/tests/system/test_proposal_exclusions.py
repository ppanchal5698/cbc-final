"""The exclusions a proposal prints are the estimator's (FR-10).

Edited on the proposal screen, line by line. Removing every one means the
proposal excludes nothing - it does not bring the defaults back.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_proposal_exclusions"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


def test_the_estimators_exclusions_print_and_none_means_none(client):
    code = client.post("/api/projects", json={"name": "Exclusions bid", "state": "IN"}).json()["code"]
    default = client.get(f"/api/projects/{code}/proposal").json()["proposal"]["exclusions"]
    assert default, "a new proposal starts from the standard exclusions"

    client.patch(f"/api/projects/{code}/proposal", json={"exclusions": ["Keying by the owner's locksmith."]})
    assert client.get(f"/api/projects/{code}/proposal").json()["proposal"]["exclusions"] == [
        "Keying by the owner's locksmith."]
    assert "Keying by the owner&#39;s locksmith." in client.get(f"/api/projects/{code}/proposal/render").text

    client.patch(f"/api/projects/{code}/proposal", json={"exclusions": []})
    assert client.get(f"/api/projects/{code}/proposal").json()["proposal"]["exclusions"] == []
    assert default[0] not in client.get(f"/api/projects/{code}/proposal/render").text
