"""Pricing module: the reference-data families, every operation pinned.

Runs on reference_store's in-memory backend, the way the reference-data suite
does: the families seed from the committed JSON on first read, edits stay in
memory, and nothing is left in Mongo or on disk. Where a write needs a whole
document, the recipe reads it first and sends it back, so the payload is real
data rather than something invented for the test.
"""
from __future__ import annotations

import pytest

from cbc.core import calc
from cbc.services import reference_store
from tests.shared import opshub_client

TEST_DB = "cbc_opshub_char_pricing"
REF = "/api/reference"


@pytest.fixture(scope="module", autouse=True)
def memory_reference():
    reference_store.use_memory({})
    calc.invalidate_reference_caches()
    try:
        yield
    finally:
        reference_store.use_memory(None)
        calc.invalidate_reference_caches()


@pytest.fixture(scope="module")
def client(memory_reference):
    with opshub_client(TEST_DB, isolated_storage=True, role="admin") as test_client:
        yield test_client


def _ok(response):
    assert 200 <= response.status_code < 300, f"{response.request.method} {response.request.url}: {response.status_code} {response.text[:300]}"
    return response


def test_margins(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/margins", _ok(client.get(f"{REF}/margins")))
    snapshots.pin("PATCH /api/reference/margins", _ok(client.patch(f"{REF}/margins", json={"bands": {"commodity": 0.27}})))


def test_tax(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/tax", _ok(client.get(f"{REF}/tax")))
    snapshots.pin("PATCH /api/reference/tax", _ok(client.patch(f"{REF}/tax", json={"rates": {"IN": 0.07}})))


def test_delete_a_reference_entry(client, snapshots) -> None:
    op = "DELETE /api/reference/{family}/entries/{key}"
    response = snapshots.pin(op, _ok(client.delete(f"{REF}/tax/entries/IN")))
    assert "IN" not in response.json().get("rates", {})
    snapshots.pin(op, client.delete(f"{REF}/margins/entries/commodity"), variant="family without entry delete")
    snapshots.pin(op, client.delete(f"{REF}/no_such_family/entries/x"), variant="unknown family")


def test_adders(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/adders", _ok(client.get(f"{REF}/adders")))
    op = "PATCH /api/reference/adders"
    snapshots.pin(op, _ok(client.patch(f"{REF}/adders", json={"items": {"Lead lined": 225.0}})))
    snapshots.pin(op, client.patch(f"{REF}/adders", json={"items": {"Lead lined": -1}}), variant="negative adder")


def test_special_margins(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/special-margins", _ok(client.get(f"{REF}/special-margins")))
    op = "PATCH /api/reference/special-margins"
    snapshots.pin(op, _ok(client.patch(f"{REF}/special-margins", json={"customers": [{"name": "Wendys", "margin": 0.3}]})))
    snapshots.pin(op, client.patch(f"{REF}/special-margins", json={"customers": [{"name": "Wendys", "margin": 2}]}), variant="margin above one")


def test_finishes(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/finishes", _ok(client.get(f"{REF}/finishes")))
    body = {"finishes": [{"us_code": "US26D", "description": "Satin chrome"}]}
    snapshots.pin("PATCH /api/reference/finishes", _ok(client.patch(f"{REF}/finishes", json=body)))


def test_frame_depths(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/frame-depths", _ok(client.get(f"{REF}/frame-depths")))
    body = {"wall_types": [{"type": "masonry", "depth": "5-3/4"}]}
    snapshots.pin("PATCH /api/reference/frame-depths", _ok(client.patch(f"{REF}/frame-depths", json=body)))


def test_frp_constants(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/frp-constants", _ok(client.get(f"{REF}/frp-constants")))
    snapshots.pin("PATCH /api/reference/frp-constants", _ok(client.patch(f"{REF}/frp-constants", json={"waste_pct": 0.1})))


def test_vendor_tiers(client, snapshots) -> None:
    response = snapshots.pin("GET /api/reference/vendor-tiers", _ok(client.get(f"{REF}/vendor-tiers")))
    hager = next(v for v in response.json()["vendors"] if v.get("key") == "hager")
    categories = hager.get("categories") or {"hinges": 0.21}
    body = {"vendor": "hager", "categories": categories}
    snapshots.pin("PATCH /api/reference/vendor-tiers", _ok(client.patch(f"{REF}/vendor-tiers", json=body)))


def test_special_nets(client, snapshots) -> None:
    snapshots.pin("GET /api/reference/special-nets", _ok(client.get(f"{REF}/special-nets")))
    body = {"items": [{"part_number": "1256", "net_price": 31.8}]}
    snapshots.pin("PATCH /api/reference/special-nets", _ok(client.patch(f"{REF}/special-nets", json=body)))


def test_lite_kit(client, snapshots) -> None:
    response = snapshots.pin("GET /api/reference/lite-kit", _ok(client.get(f"{REF}/lite-kit")))
    data = response.json()["data"]
    snapshots.pin("PUT /api/reference/lite-kit", _ok(client.put(f"{REF}/lite-kit", json={"data": data})))
    snapshots.pin("PATCH /api/reference/lite-kit", _ok(client.patch(f"{REF}/lite-kit", json={"data": data})))


def test_stock_lists(client, snapshots) -> None:
    op = "GET /api/reference/stock/{vendor}"
    response = snapshots.pin(op, _ok(client.get(f"{REF}/stock/hager")))
    snapshots.pin(op, client.get(f"{REF}/stock/acme"), variant="unknown vendor")
    first = response.json()["items"][0]
    body = {"items": [{"part_number": first["part_number"], "description": first.get("description")}]}
    snapshots.pin("PATCH /api/reference/stock/{vendor}", _ok(client.patch(f"{REF}/stock/hager", json=body)))


def test_custom_other_matrix(client, snapshots) -> None:
    response = snapshots.pin("GET /api/reference/custom-other-matrix", _ok(client.get(f"{REF}/custom-other-matrix")))
    body = {"data": response.json()}
    snapshots.pin("PUT /api/reference/custom-other-matrix", _ok(client.put(f"{REF}/custom-other-matrix", json=body)))
