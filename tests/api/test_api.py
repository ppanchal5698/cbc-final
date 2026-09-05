"""API tests against a real MongoDB.

These run against the docker-compose instance on a throwaway database, so they
exercise the actual queries and indexes rather than a mock that agrees with
whatever the code happens to do.

    docker compose up -d && python -m pytest tests/api -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bson import ObjectId
from pymongo import MongoClient

from cbc.config import settings
from tests.shared import ROOT, opshub_client  # noqa: E402

TEST_DB = "cbc_opshub_test"
FIXTURE = ROOT / "tests" / "fixtures" / "pdfs" / "1_Architectural.pdf"


def _finish_active_pipeline_jobs(code: str) -> None:
    """Clear queued/running pipeline jobs so phase-boundary routes can enqueue."""
    raw = MongoClient(settings.mongodb_uri)[TEST_DB]
    project_id = ObjectId(
        raw.projects.find_one({"code": code}, {"_id": 1})["_id"]
    )
    raw.jobs.update_many(
        {"projectId": project_id, "status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "done", "finishedAt": datetime.now(timezone.utc)}},
    )


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def project(client):
    response = client.post(
        "/api/projects",
        json={
            "name": "Burger King 2379 test",
            "brand": "Burger King",
            "location": "Cortlandt Manor, NY",
            "state": "NY",
            "gc": "Cortlandt Builders LLC",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── health and projects ─────────────────────────────────────────────────────


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert "NFR-1" in body["sends"]


def test_project_gets_a_code_and_a_scaffold(client, project):
    assert project["code"].startswith("CBC-")
    assert project["stage"] == "intake"
    assert (settings.storage_root / project["slug"] / "uploads" / "raw").is_dir()


def test_project_lookup_by_code_and_slug(client, project):
    assert client.get(f"/api/projects/{project['code']}").json()["id"] == project["id"]
    assert client.get(f"/api/projects/{project['slug']}").json()["id"] == project["id"]
    assert client.get("/api/projects/CBC-000000").status_code == 404


def test_project_codes_do_not_collide(client):
    first = client.post("/api/projects", json={"name": "Collision one"}).json()
    second = client.post("/api/projects", json={"name": "Collision two"}).json()
    assert first["code"] != second["code"]
    assert first["slug"] != second["slug"]


# ── documents ───────────────────────────────────────────────────────────────


def test_upload_rejects_non_pdf(client, project):
    response = client.post(
        f"/api/projects/{project['code']}/documents",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )
    assert response.status_code == 415


def test_upload_stores_the_file_and_enqueues_extraction(client, project):
    if not FIXTURE.exists():
        pytest.skip("bid-set fixture not present")

    response = client.post(
        f"/api/projects/{project['code']}/documents",
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["document"]["pages"] == 30
    assert (settings.repo_root / body["document"]["path"]).exists()

    # Uploading a plan is what notifies Claude Code.
    assert body["job"]["type"] == "extract_bid_set"
    assert body["job"]["status"] == "queued"


def test_page_size_matches_the_drawing(client, project):
    if not FIXTURE.exists():
        pytest.skip("bid-set fixture not present")
    documents = client.get(f"/api/projects/{project['code']}/documents").json()["documents"]
    document_id = documents[0]["id"]

    size = client.get(
        f"/api/projects/{project['code']}/documents/{document_id}/page/14/size"
    ).json()
    assert (size["width"], size["height"]) == (2592.0, 1728.0)


def test_raw_pdf_is_served(client, project):
    if not FIXTURE.exists():
        pytest.skip("bid-set fixture not present")
    documents = client.get(f"/api/projects/{project['code']}/documents").json()["documents"]
    response = client.get(f"/api/projects/{project['code']}/documents/{documents[0]['id']}/file")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


# ── line items ──────────────────────────────────────────────────────────────


def test_line_item_lifecycle(client, project):
    code = project["code"]

    created = client.post(
        f"/api/projects/{code}/line-items",
        json={"mark": "101", "description": "HM flush door", "size": "3-0 x 7-0", "qty": 1},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "by_hand"
    assert item["addedByHand"] is True
    # The signed-in caller, taken from X-Actor - not a default. A hand-added line
    # is confirmed on arrival because a human typed it, so it records which human.
    assert item["confirmedBy"] == "test@example.com"

    patched = client.patch(
        f"/api/projects/{code}/line-items/{item['id']}", json={"qty": 3, "finish": "US26D"}
    ).json()
    assert patched["qty"] == 3
    assert patched["finish"] == "US26D"

    listing = client.get(f"/api/projects/{code}/line-items").json()
    assert listing["counts"]["all"] >= 1
    assert listing["counts"]["by_hand"] >= 1

    assert client.delete(f"/api/projects/{code}/line-items/{item['id']}").status_code == 204


def test_unknown_filter_is_rejected(client, project):
    response = client.get(f"/api/projects/{project['code']}/line-items?filter=nonsense")
    assert response.status_code == 400


def test_continue_to_quote_writes_the_confirmed_state_to_disk(client, project):
    code, slug = project["code"], project["slug"]
    _finish_active_pipeline_jobs(code)
    client.post(
        f"/api/projects/{code}/line-items",
        json={"mark": "900", "description": "Hand-added opening", "qty": 2},
    )

    response = client.post(f"/api/projects/{code}/line-items/continue-to-quote")
    assert response.status_code == 200
    assert response.json()["job"]["type"] == "match_and_price"

    # Claude's next phase must read what the estimator confirmed.
    exported = settings.storage_root / slug / "extracted" / "door_schedule.json"
    assert exported.exists()
    import json

    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert any(o["mark"] == "900" for o in payload["openings"])


# ── quote ───────────────────────────────────────────────────────────────────


def test_quote_line_math_matches_calc_engine(client, project):
    code = project["code"]
    created = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": "HM flush door", "division": "08 11 00", "qty": 3, "cost": 412.00},
    )
    assert created.status_code == 201
    line = created.json()["line"]

    # Commodity band: 27% -> divisor 0.73
    assert line["margin"] == pytest.approx(0.27)
    assert line["sell"] == pytest.approx(round(412.00 / 0.73, 2))
    # From the unrounded unit price, not the displayed one: rounding the unit
    # first and multiplying put up to half a cent per unit into the extension.
    assert line["extended"] == pytest.approx(round(412.00 / 0.73 * 3, 2))


def test_editing_margin_recomputes_and_records_the_override(client, project):
    code = project["code"]
    line = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": "Override me", "division": "08 11 00", "qty": 1, "cost": 100.0},
    ).json()["line"]

    updated = client.patch(
        f"/api/projects/{code}/quote/lines/{line['id']}",
        json={"margin": 0.40, "overrideReason": "bought via SecLock at higher cost"},
    ).json()["line"]

    assert updated["margin"] == pytest.approx(0.40)
    assert updated["sell"] == pytest.approx(round(100.0 / 0.60, 2))
    assert updated["marginOverridden"] is True
    assert updated["overrideReason"] == "bought via SecLock at higher cost"


def test_unpriced_line_stays_unpriced(client, project):
    """A manual or awaiting-quote line must never be silently valued at zero."""
    code = project["code"]
    line = client.post(
        f"/api/projects/{code}/quote/lines",
        json={"description": "Awaiting vendor quote", "division": "08 71 00", "qty": 2},
    ).json()["line"]

    assert line["cost"] is None
    assert line["sell"] is None
    assert line["extended"] is None


def test_tax_follows_the_project_state(client, project):
    code = project["code"]

    ny = client.get(f"/api/projects/{code}/quote").json()["totals"]
    assert ny["taxJurisdiction"] == "NY"
    assert ny["taxRate"] == 0.0, "only Ohio and Kentucky are taxed"

    ohio = client.patch(
        f"/api/projects/{code}/quote/settings", json={"taxJurisdiction": "OH"}
    ).json()["totals"]
    assert ohio["taxRate"] == 0.08
    assert ohio["tax"] == pytest.approx(round(ohio["subtotal"] * 0.08, 2))
    assert ohio["grandTotal"] == pytest.approx(round(ohio["subtotal"] + ohio["tax"], 2))

    client.patch(f"/api/projects/{code}/quote/settings", json={"taxJurisdiction": "NY"})


def test_freight_is_tbd_until_set(client, project):
    totals = client.get(f"/api/projects/{project['code']}/quote").json()["totals"]
    assert totals["freight"] is None
    assert "TBD" in totals["freightNote"]


def test_quote_groups_by_division(client, project):
    body = client.get(f"/api/projects/{project['code']}/quote").json()
    divisions = {group["division"] for group in body["groups"]}
    assert "08 11 00" in divisions
    for group in body["groups"]:
        assert group["subtotal"] == pytest.approx(
            round(sum(line["extended"] or 0 for line in group["lines"]), 2)
        )


# ── catalog and price books ─────────────────────────────────────────────────


def test_catalog_search_and_crud(client):
    created = client.post(
        "/api/catalog/products",
        json={
            "part": "TEST-PART-1",
            "description": "Test grab bar",
            "manufacturer": "Bobrick",
            "division": "10 28 00",
            "cost": 50.0,
        },
    )
    assert created.status_code == 201
    product = created.json()
    # Accessories band is 56%, so sell derives to cost / 0.44
    assert product["sellAt"] == pytest.approx(round(50.0 / 0.44, 2))

    duplicate = client.post(
        "/api/catalog/products", json={"part": "TEST-PART-1", "description": "again"}
    )
    assert duplicate.status_code == 409

    found = client.get("/api/catalog/products?q=TEST-PART").json()
    assert any(p["part"] == "TEST-PART-1" for p in found["products"])

    client.patch(f"/api/catalog/products/{product['id']}", json={"cost": 60.0})
    assert client.get(f"/api/catalog/products/{product['id']}").json()["product"]["cost"] == 60.0
    assert client.delete(f"/api/catalog/products/{product['id']}").status_code == 204


def test_price_book_multiplier_change_reprices_its_parts(client):
    book = client.post(
        "/api/price-books",
        json={"vendor": "testvendor", "program": "Test program", "multiplier": 0.5},
    ).json()

    client.post(
        "/api/catalog/products",
        json={
            "part": "TEST-MULT-1",
            "description": "Repriced by the program",
            "division": "08 71 00",
            "listPrice": 200.0,
            "multiplier": 0.5,
            "cost": 100.0,
            "priceBookId": book["id"],
        },
    )

    client.patch(f"/api/price-books/{book['id']}", json={"multiplier": 0.25})

    repriced = client.get("/api/catalog/products?q=TEST-MULT-1").json()["products"][0]
    assert repriced["multiplier"] == 0.25
    assert repriced["cost"] == pytest.approx(50.0), "cost must follow list x multiplier"


def test_deleting_a_price_book_orphans_rather_than_destroys_parts(client):
    book = client.post(
        "/api/price-books", json={"vendor": "doomedvendor", "multiplier": 0.4}
    ).json()
    client.post(
        "/api/catalog/products",
        json={"part": "TEST-ORPHAN-1", "description": "Survivor", "priceBookId": book["id"]},
    )

    assert client.delete(f"/api/price-books/{book['id']}").status_code == 204

    survivor = client.get("/api/catalog/products?q=TEST-ORPHAN-1").json()["products"]
    assert len(survivor) == 1, "a live quote may still point at this part"
    assert survivor[0]["priceBookId"] is None


def test_stale_price_books_are_reported(client):
    client.post(
        "/api/price-books",
        json={"vendor": "stalevendor", "multiplier": 0.5, "effective": "2017-01-01"},
    )
    body = client.get("/api/price-books").json()
    assert body["counts"]["stale"] >= 1
    assert body["stewardship"]["owner"] is None, "NFR-10 is open; do not fake an owner"


def test_a_mid_age_price_book_follows_the_review_window(client):
    from datetime import date, timedelta

    from cbc.services import freshness as freshness_settings

    effective = (date.today() - timedelta(days=400)).isoformat()
    client.post(
        "/api/price-books",
        json={"vendor": "windowvendor", "multiplier": 0.5, "effective": effective},
    )

    def book():
        books = client.get("/api/price-books").json()["priceBooks"]
        return next(row for row in books if row["vendor"] == "windowvendor")

    assert book()["stale"] is False

    try:
        saved = client.put(
            "/api/settings/freshness",
            json={"catalogStaleMonths": 6, "discardAfterMonths": 12},
        )
        assert saved.status_code == 200, saved.text
        freshness_settings.clear_cache()
        assert book()["stale"] is True
    finally:
        client.put(
            "/api/settings/freshness",
            json={"catalogStaleMonths": 24, "discardAfterMonths": 30},
        )
        freshness_settings.clear_cache()


# ── proposal ────────────────────────────────────────────────────────────────


def test_proposal_builds_from_the_quote(client, project):
    body = client.get(f"/api/projects/{project['code']}/proposal").json()
    assert body["proposal"]["validityDays"] == 30
    assert body["proposal"]["exclusions"]
    assert body["sections"], "expected at least one priced section"
    assert body["readiness"]["blocking"] is False


def test_proposal_markup_lifts_unit_prices(client, project):
    code = project["code"]
    plain = client.get(f"/api/projects/{code}/proposal").json()
    base_total = plain["totals"]["grandTotal"]

    client.patch(f"/api/projects/{code}/proposal", json={"markup": 0.05})
    marked = client.get(f"/api/projects/{code}/proposal").json()

    assert marked["proposal"]["markup"] == 0.05
    assert marked["totals"]["grandTotal"] > base_total
    client.patch(f"/api/projects/{code}/proposal", json={"markup": 0.0})


def test_proposal_renders_html_with_the_terms(client, project):
    html = client.get(f"/api/projects/{project['code']}/proposal/render").text
    assert "Hamilton Parker purchase order required" in html
    assert "Supply-only material" in html
    assert "Ohio and Kentucky only" in html


def test_marking_complete_does_not_send(client, project):
    body = client.post(f"/api/projects/{project['code']}/proposal/complete").json()
    assert body["sent"] is False
    assert "Nothing has been sent" in body["message"]


# ── jobs ────────────────────────────────────────────────────────────────────


def test_duplicate_job_is_not_queued_twice(client, project):
    _finish_active_pipeline_jobs(project["code"])
    first = client.post(f"/api/projects/{project['code']}/line-items/rerun").json()["job"]
    second = client.post(f"/api/projects/{project['code']}/line-items/rerun").json()["job"]
    assert first["id"] == second["id"], "a double click must not queue two extractions"


def test_continue_to_quote_returns_409_when_pipeline_active(client, project):
    code = project["code"]
    _finish_active_pipeline_jobs(code)
    client.post(f"/api/projects/{code}/line-items/rerun")

    response = client.post(f"/api/projects/{code}/line-items/continue-to-quote")
    assert response.status_code == 409
    body = response.json()["detail"]
    assert "already in progress" in body["message"]
    assert body["activeJob"]["type"] == "rerun_extraction"


def test_jobs_are_listed_for_a_project(client, project):
    body = client.get(f"/api/jobs?project={project['code']}").json()
    assert body["jobs"]
    assert {job["type"] for job in body["jobs"]} & {
        "extract_bid_set",
        "rerun_extraction",
        "match_and_price",
    }


def test_audit_trail_records_both_actors(client, project):
    from pymongo import MongoClient as _Client

    raw = _Client(settings.mongodb_uri)[TEST_DB]
    actions = raw.auditLog.distinct("action")
    assert "project.create" in actions
    assert "quote.line_edit" in actions


def test_a_net_program_is_not_repriced_by_a_multiplier(client):
    """Multiplying a net discounts a cost CBC already pays a second time.

    Bobrick is bought on a flat net program - vendor_tiers records no multiplier
    and says so - so its sheet quotes costs, not list figures. Setting a
    multiplier on that book must leave the parts alone.
    """
    book = client.post(
        "/api/price-books",
        json={"vendor": "bobrick", "program": "HP 2017 program NET"},
    ).json()
    client.patch(f"/api/price-books/{book['id']}", json={"filename": "bobrick_hp_program_net.xlsx"})

    client.post(
        "/api/catalog/products",
        json={
            "part": "TEST-NET-1",
            "description": "Priced off a net program sheet",
            "manufacturer": "bobrick",
            "listPrice": 40.0,
            "cost": 40.0,
            "priceBookId": book["id"],
        },
    )

    client.patch(f"/api/price-books/{book['id']}", json={"multiplier": 0.25})

    part = client.get("/api/catalog/products?q=TEST-NET-1").json()["products"][0]
    assert part["cost"] == pytest.approx(40.0), "a net must survive a multiplier change"


def test_a_part_marked_net_is_skipped_even_on_a_list_book(client):
    """The per-row guard, for a book whose sheet is not itself classified."""
    book = client.post(
        "/api/price-books",
        json={"vendor": "mixedvendor", "program": "Mixed", "multiplier": 0.5},
    ).json()
    made = client.post(
        "/api/catalog/products",
        json={
            "part": "TEST-NET-2",
            "description": "A net row on an otherwise list book",
            "listPrice": 40.0,
            "cost": 40.0,
            "priceBookId": book["id"],
        },
    ).json()
    client.patch(f"/api/catalog/products/{made['id']}", json={"priceBasis": "net"})

    client.patch(f"/api/price-books/{book['id']}", json={"multiplier": 0.25})

    part = client.get("/api/catalog/products?q=TEST-NET-2").json()["products"][0]
    assert part["cost"] == pytest.approx(40.0)
