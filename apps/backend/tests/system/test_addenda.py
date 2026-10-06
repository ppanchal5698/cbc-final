"""The addendum log (FR-14, requirements 6.4).

Number, issue date, changed drawings and specs, a moved bid date, changed bid
forms. An addendum PDF uploaded to the bid logs itself; one announced by phone is
logged by hand. A moved bid date moves the bid's, and the proposal acknowledges
every addendum by number - the line bid forms ask for.
"""
from __future__ import annotations

import pytest

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_addenda"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def code(client) -> str:
    response = client.post("/api/projects", json={"name": "Addenda bid", "state": "OH", "bidDue": "2026-10-13"})
    assert response.status_code == 201, response.text
    return response.json()["code"]


def test_an_addendum_is_logged_by_number(client, code):
    first = client.post(f"/api/projects/{code}/addenda", json={"notes": "phoned in by the GC"})
    assert first.status_code == 201 and first.json()["number"] == 1
    assert client.post(f"/api/projects/{code}/addenda", json={"number": 1}).status_code == 409

    second = client.post(f"/api/projects/{code}/addenda", json={
        "issuedOn": "2026-09-30", "changedDocuments": "A601, A602; section 08 71 00",
        "newBidDue": "2026-10-20", "changedForms": "bid form page 2",
    }).json()
    assert second["number"] == 2 and second["changedDocuments"].startswith("A601")

    bid = client.get(f"/api/projects/{code}").json()
    assert bid["bidDue"].startswith("2026-10-20"), "the addendum moved the bid date"
    assert [a["number"] for a in bid["addenda"]] == [1, 2]
    assert bid["addenda"][1]["previousBidDue"].startswith("2026-10-13")


def test_an_addendum_is_completed_later(client, code):
    updated = client.patch(f"/api/projects/{code}/addenda/1", json={"issuedOn": "2026-09-25"})
    assert updated.status_code == 200 and updated.json()["issuedOn"].startswith("2026-09-25")
    assert client.patch(f"/api/projects/{code}/addenda/9", json={"notes": "x"}).status_code == 404


def test_the_proposal_acknowledges_each_addendum(client, code):
    html = client.get(f"/api/projects/{code}/proposal/render").text
    assert "Addenda acknowledged" in html
    assert "No. 1 (2026-09-25), No. 2 (2026-09-30)" in html


# One blank page: enough for an upload to count, open and store.
ONE_PAGE = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")


def test_an_uploaded_addendum_logs_itself(client, code):
    upload = client.post(
        f"/api/projects/{code}/documents",
        files={"file": ("addendum-3.pdf", ONE_PAGE, "application/pdf")},
        data={"kind": "addendum"},
    )
    assert upload.status_code == 201, upload.text
    logged = client.get(f"/api/projects/{code}").json()["addenda"][-1]
    assert (logged["number"], logged["filename"], logged["version"]) == (3, "addendum-3.pdf", upload.json()["version"])
    assert logged["documentId"] == upload.json()["document"]["id"]
