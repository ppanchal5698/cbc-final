"""Extraction module: line items and alternates, every operation pinned.

Runs in file order against one throwaway bid, the way the estimator works it:
add lines, edit, confirm, group into an alternate, hand off to pricing, re-run.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from bson import ObjectId

from cbc.shared.persistence import names
from tests.shared import mongo_client, opshub_client

TEST_DB = "cbc_opshub_char_extraction"
LINES = "/api/projects/{code}/line-items"
ALTS = "/api/projects/{code}/alternates"


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def bid(client) -> dict:
    response = client.post("/api/projects", json={"name": "Characterization - extraction", "state": "OH"})
    assert response.status_code == 201, response.text
    return {"code": response.json()["code"]}


def _url(template: str, bid: dict, **ids: str) -> str:
    return template.format(code=bid["code"], **ids)


def _finish_pipeline_jobs(code: str) -> None:
    """Phase-boundary routes refuse while another pipeline job is active."""
    raw = mongo_client()
    try:
        database = raw[TEST_DB]
        project_id = ObjectId(database[names.BID_REQUESTS].find_one({"code": code}, {"_id": 1})["_id"])
        database.jobs.update_many(
            {"projectId": project_id, "status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "done", "finishedAt": datetime.now(timezone.utc)}},
        )
    finally:
        raw.close()


def test_list_line_items_on_an_empty_bid(client, bid, snapshots) -> None:
    op = f"GET {LINES}"
    snapshots.pin(op, client.get(_url(LINES, bid)))
    snapshots.pin(op, client.get(_url(LINES, bid), params={"filter": "nonsense"}), variant="unknown filter")


def test_add_line_items_by_hand(client, bid, snapshots) -> None:
    op = f"POST {LINES}"
    first = snapshots.pin(op, client.post(_url(LINES, bid), json={"mark": "01", "description": "HM door 3070", "qty": 1}))
    second = client.post(_url(LINES, bid), json={"mark": "02", "description": "HM frame 3070", "qty": 1})
    assert first.status_code == second.status_code == 201
    assert first.json()["status"] == "by_hand" and first.json()["confidence"] == 1.0
    bid["item"], bid["other"] = first.json()["id"], second.json()["id"]


def test_edit_a_line_item(client, bid, snapshots) -> None:
    op = f"PATCH {LINES}/{{item_id}}"
    snapshots.pin(op, client.patch(_url(LINES + "/{item_id}", bid, item_id=bid["item"]), json={"notes": "per A2.2"}))
    snapshots.pin(op, client.patch(_url(LINES + "/{item_id}", bid, item_id="0" * 24), json={"notes": "x"}), variant="missing item")
    snapshots.pin(op, client.patch(_url(LINES + "/{item_id}", bid, item_id="not-an-id"), json={"notes": "x"}), variant="malformed id")


def test_confirm_one_line_item(client, bid, snapshots) -> None:
    snapshots.pin(f"POST {LINES}/{{item_id}}/confirm", client.post(_url(LINES + "/{item_id}/confirm", bid, item_id=bid["item"])))


def test_confirm_all(client, bid, snapshots) -> None:
    snapshots.pin(f"POST {LINES}/confirm-all", client.post(_url(LINES + "/confirm-all", bid)))


def test_bulk_action(client, bid, snapshots) -> None:
    op = f"POST {LINES}/bulk"
    snapshots.pin(op, client.post(_url(LINES + "/bulk", bid), json={"ids": [bid["other"]], "action": "confirm"}))
    snapshots.pin(op, client.post(_url(LINES + "/bulk", bid), json={"ids": [bid["other"]], "action": "archive"}), variant="unknown action")


def test_resolve_a_duplicate(client, bid, snapshots) -> None:
    op = f"POST {LINES}/{{item_id}}/resolve-duplicate"
    url = _url(LINES + "/{item_id}/resolve-duplicate", bid, item_id=bid["item"])
    snapshots.pin(op, client.post(url, json={"keep": "both"}))
    snapshots.pin(op, client.post(url, json={"keep": "neither"}), variant="bad keep")


def test_list_alternates(client, bid, snapshots) -> None:
    snapshots.pin(f"GET {ALTS}", client.get(_url(ALTS, bid)))


def test_create_an_alternate(client, bid, snapshots) -> None:
    op = f"POST {ALTS}"
    snapshots.pin(op, client.post(_url(ALTS, bid), json={"name": "Alternate 1"}))
    snapshots.pin(op, client.post(_url(ALTS, bid), json={"name": "Alternate 1"}), variant="duplicate name")


def test_assign_lines_to_an_alternate(client, bid, snapshots) -> None:
    op = f"POST {ALTS}/assign"
    url = _url(ALTS + "/assign", bid)
    response = snapshots.pin(op, client.post(url, json={"ids": [bid["item"]], "alternate": "Alternate 1", "scope": "line-items"}))
    assert response.json() == {"moved": 1, "alternate": "Alternate 1"}
    snapshots.pin(op, client.post(url, json={"alternate": "Alternate 1"}), variant="no ids")
    snapshots.pin(op, client.post(url, json={"ids": [bid["item"]], "scope": "everything"}), variant="bad scope")


def test_continue_to_quote(client, bid, snapshots) -> None:
    op = f"POST {LINES}/continue-to-quote"
    response = snapshots.pin(op, client.post(_url(LINES + "/continue-to-quote", bid)))
    assert response.json()["job"]["type"] == "match_and_price"
    snapshots.pin(f"POST {LINES}/rerun", client.post(_url(LINES + "/rerun", bid)), variant="while pricing is queued")
    _finish_pipeline_jobs(bid["code"])


def test_rerun_extraction(client, bid, snapshots) -> None:
    response = snapshots.pin(f"POST {LINES}/rerun", client.post(_url(LINES + "/rerun", bid)))
    assert response.json()["job"]["type"] == "rerun_extraction"
    _finish_pipeline_jobs(bid["code"])


def test_delete_a_line_item(client, bid, snapshots) -> None:
    op = f"DELETE {LINES}/{{item_id}}"
    snapshots.pin(op, client.delete(_url(LINES + "/{item_id}", bid, item_id=bid["other"])))
    snapshots.pin(op, client.delete(_url(LINES + "/{item_id}", bid, item_id=bid["other"])), variant="already deleted")
