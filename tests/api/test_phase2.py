"""Phase 2 API tests: bulk actions, calls, alternates, versions and the hand-off.

The hand-off tests matter most. Phase 2 is the first time the system routes a
finished bid to a person, and NFR-1 says the copilot must still not send.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cbc.config import settings
from tests.shared import ROOT, opshub_client  # noqa: E402

TEST_DB = "cbc_opshub_test_phase2"
FIXTURE = ROOT / "tests" / "fixtures" / "pdfs" / "1_Architectural.pdf"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def project(client):
    response = client.post(
        "/api/projects",
        json={
            "name": "Phase two test bid",
            "brand": "Burger King",
            "state": "OH",
            "gc": "Cortlandt Builders LLC",
            "initiator": "Rebecca Gabrich",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_line(client, code: str, mark: str, **extra) -> dict:
    response = client.post(
        f"/api/projects/{code}/line-items",
        json={"mark": mark, "description": f"Opening {mark}", "qty": 1, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── bulk actions ────────────────────────────────────────────────────────────


def test_bulk_confirm_and_delete(client, project):
    code = project["code"]
    ids = [add_line(client, code, mark)["id"] for mark in ("B1", "B2", "B3")]

    confirmed = client.post(
        f"/api/projects/{code}/line-items/bulk", json={"ids": ids, "action": "confirm"}
    ).json()
    assert confirmed["requested"] == 3

    listing = client.get(f"/api/projects/{code}/line-items").json()
    marks = {item["mark"]: item["status"] for item in listing["lineItems"]}
    assert all(marks[m] == "clear" for m in ("B1", "B2", "B3"))

    removed = client.post(
        f"/api/projects/{code}/line-items/bulk", json={"ids": ids, "action": "delete"}
    ).json()
    assert removed["affected"] == 3
    assert client.get(f"/api/projects/{code}/line-items").json()["counts"]["all"] == 0


def test_bulk_rejects_an_unknown_action(client, project):
    response = client.post(
        f"/api/projects/{project['code']}/line-items/bulk",
        json={"ids": ["6a8eb08574bb5c34d060f353"], "action": "vaporise"},
    )
    assert response.status_code == 422


def test_bulk_cannot_reach_another_bid(client, project):
    """A stray id from another project must not be touched."""
    other = client.post("/api/projects", json={"name": "Other bid"}).json()
    stray = add_line(client, other["code"], "X1")["id"]
    mine = add_line(client, project["code"], "M1")["id"]

    result = client.post(
        f"/api/projects/{project['code']}/line-items/bulk",
        json={"ids": [mine, stray], "action": "delete"},
    ).json()

    assert result["affected"] == 1, "only the line on this project may be deleted"
    assert client.get(f"/api/projects/{other['code']}/line-items").json()["counts"]["all"] == 1


# ── calls and notes ─────────────────────────────────────────────────────────


def test_calls_lifecycle(client, project):
    code = project["code"]

    call = client.post(
        f"/api/projects/{code}/calls",
        json={"kind": "call", "text": "Spoke to the GC about the alternates.", "org": "Cortlandt"},
        headers={"X-Actor": "estimator@cbc.com"},
    )
    assert call.status_code == 201
    assert call.json()["who"] == "estimator@cbc.com"

    rfi = client.post(
        f"/api/projects/{code}/calls",
        json={"kind": "rfi", "text": "Fire ratings missing on A2.2.", "ref": "Extraction & entry"},
    ).json()

    listing = client.get(f"/api/projects/{code}/calls").json()
    assert listing["count"] == 2
    assert listing["openRfis"] == 1

    client.post(f"/api/projects/{code}/calls/{rfi['id']}/resolve")
    assert client.get(f"/api/projects/{code}/calls").json()["openRfis"] == 0


def test_only_an_rfi_can_be_resolved(client, project):
    note = client.post(
        f"/api/projects/{project['code']}/calls", json={"kind": "note", "text": "Just a note."}
    ).json()
    response = client.post(f"/api/projects/{project['code']}/calls/{note['id']}/resolve")
    assert response.status_code == 400


def test_empty_note_is_rejected(client, project):
    response = client.post(
        f"/api/projects/{project['code']}/calls", json={"kind": "note", "text": ""}
    )
    assert response.status_code == 422


# ── alternates ──────────────────────────────────────────────────────────────


def test_alternates_start_with_only_a_base_bid(client, project):
    body = client.get(f"/api/projects/{project['code']}/alternates").json()
    assert [a["label"] for a in body["alternates"]] == ["Base bid"]
    assert body["alternates"][0]["isBase"] is True
    assert "Matrix 4.1" in body["pending"], "the open question must stay visible"


def test_an_alternate_does_not_inherit_the_base_bid(client, project):
    """Whether an alternate inherits confirmations is unanswered - so it starts empty."""
    code = project["code"]
    add_line(client, code, "A1")

    created = client.post(f"/api/projects/{code}/alternates", json={"name": "Alternate 1"})
    assert created.status_code == 201
    assert created.json()["lineItemCount"] == 0

    duplicate = client.post(f"/api/projects/{code}/alternates", json={"name": "Alternate 1"})
    assert duplicate.status_code == 409


def test_lines_move_into_an_alternate_and_totals_stay_separate(client, project):
    code = project["code"]
    base = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": "Base line", "division": "08 11 00", "qty": 1, "cost": 100.0},
    ).json()["line"]
    alt = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": "Alternate line", "division": "08 11 00", "qty": 1, "cost": 200.0},
    ).json()["line"]

    moved = client.post(
        f"/api/projects/{code}/alternates/assign",
        params={"alternate": "Alternate 1", "scope": "quote-lines"},
        json=[alt["id"]],
    )
    assert moved.status_code == 200
    assert moved.json()["moved"] == 1

    groups = {a["label"]: a for a in client.get(f"/api/projects/{code}/alternates").json()["alternates"]}
    assert groups["Base bid"]["quoteLineCount"] >= 1
    assert groups["Alternate 1"]["quoteLineCount"] == 1
    # 100/0.73 vs 200/0.73 - each group totals only its own lines.
    assert groups["Alternate 1"]["subtotal"] == pytest.approx(round(200 / 0.73, 2))
    assert base["id"] != alt["id"]


def test_assign_accepts_the_frontend_object_body(client, project):
    """The extraction screen posts {ids, alternate, scope} — not query params."""
    code = project["code"]
    item = client.post(
        f"/api/projects/{code}/line-items",
        json={"mark": "D1", "description": "Door", "division": "08 11 00", "qty": 1},
    ).json()

    moved = client.post(
        f"/api/projects/{code}/alternates/assign",
        json={"ids": [item["id"]], "alternate": "Alternate 1", "scope": "line-items"},
    )
    assert moved.status_code == 200
    assert moved.json() == {"moved": 1, "alternate": "Alternate 1"}

    alt_only = client.get(
        f"/api/projects/{code}/line-items?alternate=Alternate%201"
    ).json()["lineItems"]
    assert any(row["id"] == item["id"] for row in alt_only)


def test_assign_accepts_ids_as_query_parameters(client, project):
    code = project["code"]
    item = client.post(
        f"/api/projects/{code}/line-items",
        json={"mark": "D2", "description": "Door", "division": "08 11 00", "qty": 1},
    ).json()

    moved = client.post(
        f"/api/projects/{code}/alternates/assign",
        params={"ids": [item["id"]], "alternate": "Alternate 1", "scope": "line-items"},
    )
    assert moved.status_code == 200
    assert moved.json()["moved"] == 1

    alt_only = client.get(
        f"/api/projects/{code}/line-items?alternate=Alternate%201"
    ).json()["lineItems"]
    assert any(row["id"] == item["id"] for row in alt_only)


def test_assign_reports_zero_when_lines_are_already_in_the_group(client, project):
    code = project["code"]
    item = client.post(
        f"/api/projects/{code}/line-items",
        json={"mark": "D3", "description": "Door", "division": "08 11 00", "qty": 1},
    ).json()
    payload = {"ids": [item["id"]], "alternate": "Alternate 1", "scope": "line-items"}

    assert client.post(f"/api/projects/{code}/alternates/assign", json=payload).json()["moved"] == 1
    assert client.post(f"/api/projects/{code}/alternates/assign", json=payload).json()["moved"] == 0


def test_line_items_can_be_filtered_by_alternate(client, project):
    code = project["code"]
    everything = client.get(f"/api/projects/{code}/line-items").json()["lineItems"]
    base_only = client.get(f"/api/projects/{code}/line-items?alternate=").json()["lineItems"]
    assert len(base_only) == len([i for i in everything if not i.get("alternateGroup")])


# ── versions ────────────────────────────────────────────────────────────────


def test_a_version_freezes_prior_work(client, project):
    code = project["code"]
    add_line(client, code, "V1")
    before = client.get(f"/api/projects/{code}/line-items").json()["counts"]["all"]

    created = client.post(f"/api/projects/{code}/versions", json={"reason": "Addendum 1"})
    assert created.status_code == 201
    version = created.json()["version"]["version"]

    # Change the live state; the snapshot must not follow it.
    add_line(client, code, "V2")
    client.post(f"/api/projects/{code}/line-items/confirm-all")

    stored = client.get(f"/api/projects/{code}/versions/{version}").json()
    assert stored["lineItemCount"] == before, "the snapshot moved with the live data"
    assert len(stored["snapshot"]["lineItems"]) == before


def test_the_diff_reports_additions_without_merging(client, project):
    code = project["code"]
    versions = client.get(f"/api/projects/{code}/versions").json()
    latest = versions["versions"][0]["version"]

    diff = client.get(f"/api/projects/{code}/versions/{latest}/diff").json()
    assert "V2" in diff["added"], "a line added after the snapshot should show as added"
    assert "Matrix 4.1" in diff["pending"]


def test_versions_start_unreconciled_and_are_marked_by_a_person(client, project):
    code = project["code"]
    listing = client.get(f"/api/projects/{code}/versions").json()
    assert listing["unreconciled"] >= 1

    latest = listing["versions"][0]["version"]
    done = client.post(
        f"/api/projects/{code}/versions/{latest}/reconcile", headers={"X-Actor": "rick"}
    ).json()
    assert done["reconciled"] is True and done["by"] == "rick"


def test_uploading_an_addendum_snapshots_and_queues_the_right_job(client, project):
    if not FIXTURE.exists():
        pytest.skip("bid-set fixture not present")
    code = project["code"]
    before = len(client.get(f"/api/projects/{code}/versions").json()["versions"])

    response = client.post(
        f"/api/projects/{code}/documents",
        files={"file": ("addendum-1.pdf", FIXTURE.read_bytes(), "application/pdf")},
        data={"kind": "addendum"},
    )
    assert response.status_code == 201
    body = response.json()

    assert body["job"]["type"] == "ingest_addendum"
    assert body["version"] is not None
    assert "not merged" in body["note"]
    assert len(client.get(f"/api/projects/{code}/versions").json()["versions"]) == before + 1


# ── tax intent ──────────────────────────────────────────────────────────────


def test_no_nexus_is_distinct_from_unset(client, project):
    """An explicit "no nexus" must not silently fall back to the project's state."""
    code = project["code"]

    unset = client.get(f"/api/projects/{code}/quote").json()["totals"]
    assert unset["taxJurisdiction"] == "OH", "unset falls back to the ship-to state"
    assert unset["taxRate"] == 0.08

    ruled = client.patch(
        f"/api/projects/{code}/quote/settings", json={"taxJurisdiction": "NONE"}
    ).json()["totals"]
    assert ruled["taxJurisdiction"] == "NONE"
    assert ruled["taxRate"] == 0.0
    assert ruled["tax"] == 0.0
    assert "no nexus" in ruled["taxNote"].lower()

    client.patch(f"/api/projects/{code}/quote/settings", json={"taxJurisdiction": "OH"})


def test_freight_can_be_quoted_and_cleared(client, project):
    code = project["code"]
    with_freight = client.patch(
        f"/api/projects/{code}/quote/settings", json={"freight": 250.0}
    ).json()["totals"]
    assert with_freight["freight"] == 250.0
    assert "quoted on this bid" in with_freight["freightNote"]

    cleared = client.patch(
        f"/api/projects/{code}/quote/settings", json={"freight": None}
    ).json()["totals"]
    assert cleared["freight"] is None
    assert "TBD" in cleared["freightNote"]


def test_lapsed_prices_are_flagged(client, project):
    """A cost from a sheet past the review window is unverified, and says so."""
    code = project["code"]
    line = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": "Priced off an old sheet", "division": "08 71 00", "cost": 50.0},
    ).json()["line"]

    from pymongo import MongoClient as _Client

    _Client(settings.mongodb_uri)[TEST_DB].quoteLines.update_one(
        {"_id": __import__("bson").ObjectId(line["id"])},
        {"$set": {"multiplierEffectiveDate": "2017-01-01"}},
    )

    body = client.get(f"/api/projects/{code}/quote").json()
    lapsed = [l for g in body["groups"] for l in g["lines"] if l["lapsed"]]
    assert lapsed, "a 2017 price book should read as lapsed"
    assert body["lapsedCount"] >= 1


# ── hand-off ────────────────────────────────────────────────────────────────


def test_hand_off_routes_to_the_initiator_and_sends_nothing(client, project):
    code = project["code"]
    result = client.post(f"/api/projects/{code}/proposal/complete", json={}).json()

    assert result["sent"] is False, "NFR-1: the copilot never sends"
    assert result["handedOffTo"] == "Rebecca Gabrich"
    assert "Nothing has been sent" in result["message"]

    # The bid now shows in that person's queue.
    assert client.get(f"/api/projects/{code}").json()["handedOffTo"] == "Rebecca Gabrich"

    # And the drafted body exists on disk as an artifact, not in an outbox.
    draft = settings.repo_root / result["draftPath"]
    assert draft.exists()
    assert "Nothing has been sent" in draft.read_text(encoding="utf-8")


def test_hand_off_without_an_initiator_says_so(client):
    """Silently routing to nobody would be worse than saying it plainly."""
    orphan = client.post("/api/projects", json={"name": "No initiator bid"}).json()
    result = client.post(
        f"/api/projects/{orphan['code']}/proposal/complete", json={}
    ).json()

    assert result["handedOffTo"] is None
    assert "nobody to route it to" in result["message"]
    assert "Nothing has been sent" in result["message"]


def test_email_draft_is_built_but_not_sent(client, project):
    draft = client.get(f"/api/projects/{project['code']}/proposal/email-draft").json()
    assert draft["sent"] is False
    assert draft["to"] == "Rebecca Gabrich"
    assert "CBC Quotation" in draft["subject"]
    assert "does not send" in draft["note"]
    assert "purchase order required" in draft["body"].lower()


def test_a_presentation_markup_keeps_the_sheet_adding_up(client, project):
    """The customer reads this sheet. Its own numbers have to reconcile.

    The markup moves every printed unit price, so the subtotal has to move with
    them - printing the quote's raw subtotal above marked-up section totals puts
    a sum on a customer-facing document that is visibly wrong.
    """
    code = project["code"]

    for markup in (0.0, 0.02, 0.05):
        client.patch(f"/api/projects/{code}/proposal", json={"markup": markup})
        body = client.get(f"/api/projects/{code}/proposal").json()
        totals = body["totals"]

        sections = round(sum(s["subtotal"] for s in body["sections"]), 2)
        assert abs(sections - totals["subtotal"]) < 0.01, markup
        assert abs(totals["subtotal"] + (totals.get("tax") or 0) - totals["grandTotal"]) < 0.01


def test_a_confirmed_hand_added_line_counts_as_cleared(client, project):
    """`status` holds provenance and review state in one field.

    A line added by hand is stored as `by_hand`, so counting the `clear` bucket
    dropped it even after the estimator confirmed it - the board and the home
    screen then under-reported how much of the bid was actually checked.
    """
    code = project["code"]

    added = client.post(
        f"/api/projects/{code}/line-items",
        json={"description": "Hand-added closer", "qty": 1},
    ).json()
    confirmed_line = client.post(
        f"/api/projects/{code}/line-items/{added['id']}/confirm"
    ).json()

    counts = client.get(f"/api/projects/{code}").json()["counts"]
    items = client.get(f"/api/projects/{code}/line-items").json()["lineItems"]
    confirmed = sum(1 for i in items if i.get("confirmedAt"))

    assert counts["clear"] == confirmed
    assert confirmed_line["status"] == "clear"
    assert confirmed_line.get("addedByHand") is True
