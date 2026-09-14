"""Quoting module: quote, proposal and operational records, every operation pinned.

The PDF route imports WeasyPrint at request time, and WeasyPrint's native
libraries exist on some machines and not others. Both outcomes are pinned with a
stand-in module, so the snapshot is the same on every platform.
"""
from __future__ import annotations

import sys
import types

import pytest

from tests.characterization._harness import finish_pipeline_jobs
from tests.shared import opshub_client

TEST_DB = "cbc_opshub_char_quoting"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def bid(client) -> dict:
    response = client.post(
        "/api/projects",
        json={"name": "Characterization - quoting", "state": "OH", "gc": "Char GC", "initiator": "Rick Sales"},
    )
    assert response.status_code == 201, response.text
    return {"code": response.json()["code"]}


def _p(bid: dict, rest: str = "") -> str:
    return f"/api/projects/{bid['code']}{rest}"


# ── quote ────────────────────────────────────────────────────────────────────


def test_get_an_empty_quote(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/quote", client.get(_p(bid, "/quote")))


def test_quote_settings(client, bid, snapshots) -> None:
    body = {"taxJurisdiction": "OH", "freight": 0, "freightNote": "TBD"}
    snapshots.pin("PATCH /api/projects/{code}/quote/settings", client.patch(_p(bid, "/quote/settings"), json=body))


def test_add_a_quote_line(client, bid, snapshots) -> None:
    body = {"description": "HM door 3070", "qty": 2, "cost": 100.0, "productType": "commodity", "division": "08"}
    response = snapshots.pin("POST /api/projects/{code}/quote/lines", client.post(_p(bid, "/quote/lines"), json=body))
    bid["line"] = response.json()["line"]["id"]
    second = client.post(_p(bid, "/quote/lines"), json={"description": "Grab bar", "qty": 1, "cost": 20.0})
    assert second.status_code == 201, second.text
    bid["other_line"] = second.json()["line"]["id"]
    snapshots.pin("GET /api/projects/{code}/quote", client.get(_p(bid, "/quote")), variant="with lines")


def test_override_a_quote_line(client, bid, snapshots) -> None:
    op = "PATCH /api/projects/{code}/quote/lines/{line_id}"
    body = {"margin": 0.3, "overrideReason": "distributor buy"}
    response = snapshots.pin(op, client.patch(_p(bid, f"/quote/lines/{bid['line']}"), json=body))
    assert response.json()["line"]["marginOverridden"] is True
    snapshots.pin(op, client.patch(_p(bid, "/quote/lines/" + "0" * 24), json={"qty": 1}), variant="missing line")


def test_delete_a_quote_line(client, bid, snapshots) -> None:
    op = "DELETE /api/projects/{code}/quote/lines/{line_id}"
    snapshots.pin(op, client.delete(_p(bid, f"/quote/lines/{bid['other_line']}")))
    snapshots.pin(op, client.delete(_p(bid, f"/quote/lines/{bid['other_line']}")), variant="already deleted")


def test_continue_to_proposal(client, bid, snapshots) -> None:
    op = "POST /api/projects/{code}/quote/continue-to-proposal"
    response = snapshots.pin(op, client.post(_p(bid, "/quote/continue-to-proposal")))
    assert response.json()["job"]["type"] == "build_proposal"
    snapshots.pin(op, client.post(_p(bid, "/quote/continue-to-proposal")), variant="build already queued")
    finish_pipeline_jobs(TEST_DB, bid["code"])


# ── proposal ─────────────────────────────────────────────────────────────────


def test_get_the_proposal(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/proposal", client.get(_p(bid, "/proposal")))


def test_update_the_proposal(client, bid, snapshots) -> None:
    op = "PATCH /api/projects/{code}/proposal"
    snapshots.pin(op, client.patch(_p(bid, "/proposal"), json={"markup": 0.05, "exclusions": ["Installation"]}))
    snapshots.pin(op, client.patch(_p(bid, "/proposal"), json={"markup": 0.5}), variant="markup above the cap")


def test_render_the_proposal(client, bid, snapshots) -> None:
    response = snapshots.pin("GET /api/projects/{code}/proposal/render", client.get(_p(bid, "/proposal/render"), params={"autoprint": True}))
    assert "<html" in response.text.lower()


def test_proposal_pdf(client, bid, snapshots, monkeypatch) -> None:
    op = "GET /api/projects/{code}/proposal/pdf"

    class HTML:
        def __init__(self, string: str, base_url: str | None = None) -> None:
            self.string = string

        def write_pdf(self) -> bytes:
            return b"%PDF-1.4 characterization"

    renderer = types.ModuleType("weasyprint")
    renderer.HTML = HTML
    monkeypatch.setitem(sys.modules, "weasyprint", renderer)
    response = snapshots.pin(op, client.get(_p(bid, "/proposal/pdf")))
    assert response.content.startswith(b"%PDF")

    monkeypatch.setitem(sys.modules, "weasyprint", None)  # import raises: no renderer
    snapshots.pin(op, client.get(_p(bid, "/proposal/pdf")), variant="no local renderer")


def test_complete_the_proposal(client, bid, snapshots) -> None:
    body = {"recipient": "Rick Sales", "note": "ready for the GC"}
    snapshots.pin("POST /api/projects/{code}/proposal/complete", client.post(_p(bid, "/proposal/complete"), json=body))


def test_email_draft_is_never_sent(client, bid, snapshots) -> None:
    response = snapshots.pin("GET /api/projects/{code}/proposal/email-draft", client.get(_p(bid, "/proposal/email-draft")))
    assert response.json()["sent"] is False


# ── operational records ──────────────────────────────────────────────────────


def test_vendor_rfqs(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/vendor-rfqs", client.get(_p(bid, "/vendor-rfqs")))
    created = snapshots.pin(
        "POST /api/projects/{code}/vendor-rfqs",
        client.post(_p(bid, "/vendor-rfqs"), json={"rfqNumber": "RFQ-001", "triggerReason": "semi-custom frame"}),
    )
    rfq = created.json()["id"]
    op = "PATCH /api/projects/{code}/vendor-rfqs/{rfq_id}"
    snapshots.pin(op, client.patch(_p(bid, f"/vendor-rfqs/{rfq}"), json={"status": "requested"}))
    snapshots.pin(op, client.patch(_p(bid, f"/vendor-rfqs/{rfq}"), json={"status": "applied"}), variant="illegal transition")
    assert client.patch(_p(bid, f"/vendor-rfqs/{rfq}"), json={"status": "awaiting"}).status_code == 200
    snapshots.pin(op, client.patch(_p(bid, f"/vendor-rfqs/{rfq}"), json={"status": "received"}), variant="received without a price")


def test_rfis(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/rfis", client.get(_p(bid, "/rfis")))
    body = {"subject": "Door 05 rating", "question": "Is opening 05 a 90-minute door?"}
    created = snapshots.pin("POST /api/projects/{code}/rfis", client.post(_p(bid, "/rfis"), json=body))
    op = "PATCH /api/projects/{code}/rfis/{rfi_id}"
    rfi = created.json()["id"]
    snapshots.pin(op, client.patch(_p(bid, f"/rfis/{rfi}"), json={"status": "sent"}))
    snapshots.pin(op, client.patch(_p(bid, f"/rfis/{rfi}"), json={"status": "answered"}), variant="answered without an answer")


def test_takeoffs(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/takeoffs", client.get(_p(bid, "/takeoffs")))
    body = {"takeoffType": "frp", "perimeterLf": 120.5, "insideCorners": 4, "outsideCorners": 2, "wallHeightFt": 8}
    snapshots.pin("POST /api/projects/{code}/takeoffs", client.post(_p(bid, "/takeoffs"), json=body))


def test_feedback_events(client, bid, snapshots) -> None:
    snapshots.pin("GET /api/projects/{code}/feedback-events", client.get(_p(bid, "/feedback-events")))
