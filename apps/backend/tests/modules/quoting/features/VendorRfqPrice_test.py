"""FR-16 end to end: a vendor's price comes back, is recorded against its line, and prices the quote.

And the RFI state machine, where answering an RFI records what the answer was.
"""
from __future__ import annotations

from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_vendor_rfq_price"
DOOR = "4070 HM door 90 min"


def _line(client, code: str, description: str) -> dict:
    quote = client.get(f"/api/projects/{code}/quote").json()
    return next(line for group in quote["groups"] for line in group["lines"] if line["description"] == description)


def test_a_received_price_applies_to_its_line_and_reprices_the_quote() -> None:
    with opshub_client(TEST_DB, isolated_storage=True) as client:
        code = client.post("/api/projects", json={"name": "Vendor RFQ price", "state": "OH"}).json()["code"]
        base = f"/api/projects/{code}"
        added = client.post(
            f"{base}/quote/lines",
            json={"description": DOOR, "division": "08 71 00", "qty": 2, "cost": 100.0, "margin": 0.27},
        )
        assert added.status_code == 201, added.text
        line = _line(client, code, DOOR)

        rfq = client.post(f"{base}/vendor-rfqs", json={"rfqNumber": "RFQ-77", "triggerReason": "customSize"}).json()
        url = f"{base}/vendor-rfqs/{rfq['id']}"
        for status in ("requested", "awaiting"):
            assert client.patch(url, json={"status": status}).status_code == 200

        assert client.patch(url, json={"status": "received"}).status_code == 400, "a price is required"
        stranger = {"status": "received", "quotedPrices": [{"estimateLineId": "0" * 24, "amount": 1}]}
        assert client.patch(url, json=stranger).status_code == 400, "only this bid's lines"

        received = client.patch(url, json={
            "status": "received",
            "quotedPrices": [{"estimateLineId": line["id"], "amount": 150.0, "leadTimeDays": 21}],
        })
        assert received.status_code == 200, received.text
        assert received.json()["quotedPrices"][0]["amount"] == 150.0
        assert _line(client, code, DOOR)["cost"] == 100.0, "receiving a price does not apply it"

        applied = client.patch(url, json={"status": "applied"})
        assert applied.status_code == 200, applied.text
        priced = _line(client, code, DOOR)
        assert priced["cost"] == 150.0
        assert priced["costSource"] == "VENDOR_RFQ"
        assert "RFQ-77" in priced["costSourceDetail"]
        assert priced["sell"] is not None and priced["sell"] > 150.0, "the quote was repriced from the new cost"

        assert client.patch(url, json={"status": "cancelled"}).status_code == 400, "applied is final"


def test_an_rfi_follows_its_states_and_is_answered_only_with_an_answer() -> None:
    with opshub_client(TEST_DB, isolated_storage=True) as client:
        code = client.post("/api/projects", json={"name": "RFI states"}).json()["code"]
        base = f"/api/projects/{code}"
        rfi = client.post(f"{base}/rfis", json={"subject": "Door 05", "question": "Is 05 rated?"}).json()
        url = f"{base}/rfis/{rfi['id']}"

        assert client.patch(url, json={"status": "answered", "answer": "Yes"}).status_code == 400, "open cannot skip sent"
        assert client.patch(url, json={"status": "sent"}).status_code == 200
        assert client.patch(url, json={"status": "answered"}).status_code == 400, "an answer is required"

        answered = client.patch(url, json={"status": "answered", "answer": "90 minutes, per A5.1"})
        assert answered.status_code == 200, answered.text
        assert answered.json()["answer"] == "90 minutes, per A5.1"
        assert client.patch(url, json={"status": "closed"}).json()["status"] == "closed"

        assert client.patch(f"{base}/rfis/{'0' * 24}", json={"status": "sent"}).status_code == 404
