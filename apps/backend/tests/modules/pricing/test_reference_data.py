"""Reference-data API + service: Mongo-backed margin framework and siblings.

Service tests use an in-memory reference_store so seed JSON is never left dirty.
API tests need Mongo and skip without it, like the rest of the API suite.
"""
from __future__ import annotations

import pytest

from cbc.modules.pricing.api import calc
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.api import reference_store
from tests.shared import TEST_ACTOR, opshub_client, mongo_client

TEST_DB = "cbc_opshub_test_reference"


@pytest.fixture(autouse=True)
def memory_reference():
    """Isolate mutations in an empty memory backend (seed-on-read)."""
    reference_store.use_memory({})
    calc.invalidate_reference_caches()
    try:
        yield
    finally:
        reference_store.use_memory(None)
        calc.invalidate_reference_caches()


# --- service level (no database) ------------------------------------------


def test_update_margins_round_trip() -> None:
    updated = reflib.update_margins(bands={"commodity": 0.30})
    band = next(b for b in updated["bands"] if b["key"] == "commodity")
    assert band["margin"] == 0.30
    assert band["divisor"] == 0.70
    assert calc.bands()["commodity"] == 0.30


def test_update_margins_accessories() -> None:
    updated = reflib.update_margins(accessories=0.5)
    assert updated["accessories_derived"] == 0.5


def test_update_margins_preserves_other_fields() -> None:
    before = reflib.load_margins()
    reflib.update_margins(bands={"commodity": 0.28})
    after = reflib.load_margins()
    assert after["formula"] == before["formula"]
    assert len(after["bands"]) == len(before["bands"])


def test_update_margins_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        reflib.update_margins(bands={"commodity": 1.5})


def test_update_margins_rejects_unknown_band() -> None:
    with pytest.raises(ValueError):
        reflib.update_margins(bands={"not_a_band": 0.3})


def test_update_tax_rates_round_trip() -> None:
    reflib.update_tax_rates(rates={"OH": 0.0825})
    assert calc.tax_rates()["OH"] == 0.0825


def test_update_tax_rates_add_and_remove() -> None:
    reflib.update_tax_rates(rates={"IN": 0.07})
    assert calc.tax_rates()["IN"] == 0.07

    reflib.update_tax_rates(remove=["IN"])
    assert "IN" not in calc.tax_rates()
    assert calc.compute_totals([{"group": "g", "ext_price": 100.0}], "IN")["tax_rate"] == 0.0


def test_update_tax_rates_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        reflib.update_tax_rates(rates={"OH": 1.5})


def test_update_hager_adders_round_trip() -> None:
    updated = reflib.update_hager_adders(items={"Lead lined": 220.0})
    row = next(r for r in updated["hager_list_adders"]["items"] if r["name"] == "Lead lined")
    assert row["list_adder"] == 220.0


def test_update_hager_adders_add_and_remove() -> None:
    reflib.update_hager_adders(items={"Custom prep": 12.5})
    assert any(r["name"] == "Custom prep" for r in reflib.load_adders()["hager_list_adders"]["items"])
    reflib.update_hager_adders(remove=["Custom prep"])
    assert not any(
        r["name"] == "Custom prep" for r in reflib.load_adders()["hager_list_adders"]["items"]
    )


def test_update_hager_adders_rejects_negative() -> None:
    with pytest.raises(ValueError):
        reflib.update_hager_adders(items={"Lead lined": -5})


def test_update_special_margins_set_value() -> None:
    updated = reflib.update_special_margins(customers=[{"name": "Wendys", "margin": 0.30}])
    row = next(c for c in updated["customers"] if c["name"] == "Wendys")
    assert row["margin"] == 0.30


def test_update_special_margins_note_only_preserves_margin() -> None:
    reflib.update_special_margins(customers=[{"name": "Wendys", "margin": 0.30}])
    reflib.update_special_margins(customers=[{"name": "Wendys", "note": "distributor buy"}])
    row = next(c for c in reflib.load_special_margins()["customers"] if c["name"] == "Wendys")
    assert row["margin"] == 0.30
    assert row["note"] == "distributor buy"


def test_update_special_margins_clear_value() -> None:
    reflib.update_special_margins(customers=[{"name": "Wendys", "margin": 0.30}])
    reflib.update_special_margins(customers=[{"name": "Wendys", "margin": None}])
    row = next(c for c in reflib.load_special_margins()["customers"] if c["name"] == "Wendys")
    assert row["margin"] is None


def test_update_special_margins_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        reflib.update_special_margins(customers=[{"name": "Wendys", "margin": 1.5}])


def test_update_finishes_edit_preserves_others() -> None:
    reflib.update_finishes(finishes=[{"us_code": "US26D", "description": "Satin chrome edited"}])
    finishes = {f["us_code"]: f for f in reflib.load_finishes()["finishes"]}
    assert finishes["US26D"]["description"] == "Satin chrome edited"
    assert finishes["US19"]["numeric_code"] != finishes["US26D"]["numeric_code"]


def test_update_finishes_add_and_remove() -> None:
    reflib.update_finishes(finishes=[{"us_code": "US14", "numeric_code": "618"}])
    assert any(f["us_code"] == "US14" for f in reflib.load_finishes()["finishes"])
    reflib.update_finishes(remove=["US14"])
    assert not any(f["us_code"] == "US14" for f in reflib.load_finishes()["finishes"])


def test_update_frame_depths_derives_inches() -> None:
    reflib.update_frame_depths(wall_types=[{"type": "masonry", "depth": "5-3/4"}])
    row = next(w for w in reflib.load_frame_depths()["wall_types"] if w["type"] == "masonry")
    assert row["depth"] == "5-3/4"
    assert row["depth_inches"] == 5.75


def test_update_frame_depths_rejects_unparseable_depth() -> None:
    with pytest.raises(ValueError):
        reflib.update_frame_depths(wall_types=[{"type": "masonry", "depth": "thick"}])


def test_update_frp_constants_completes_to_set() -> None:
    reflib.update_frp_constants(
        {
            "panel_size": "4 x 8",
            "waste_pct": 10,
            "trim_stick_length": 8,
            "adhesive_coverage_sqft_per_unit": 200,
        }
    )
    doc = reflib.load_frp_constants()
    assert doc["status"] == "SET"
    assert doc["panel_size"] == "4 x 8"


def test_update_frp_constants_partial_stays_pending() -> None:
    reflib.update_frp_constants({"waste_pct": 10})
    assert reflib.load_frp_constants()["status"] == "PENDING"


def test_update_frp_constants_clear_returns_to_pending() -> None:
    reflib.update_frp_constants(
        {
            "panel_size": "4 x 8",
            "waste_pct": 10,
            "trim_stick_length": 8,
            "adhesive_coverage_sqft_per_unit": 200,
        }
    )
    assert reflib.load_frp_constants()["status"] == "SET"
    reflib.update_frp_constants({"waste_pct": None})
    assert reflib.load_frp_constants()["status"] == "PENDING"


def test_update_frp_constants_rejects_negative() -> None:
    with pytest.raises(ValueError):
        reflib.update_frp_constants({"waste_pct": -5})


def test_seed_fills_all_families_when_empty() -> None:
    import asyncio

    seeded = asyncio.run(reference_store.ensure_reference_seed())
    assert set(seeded) == set(reference_store.FAMILIES)
    again = asyncio.run(reference_store.ensure_reference_seed())
    assert again == []


# --- API level (needs Mongo) ----------------------------------------------


@pytest.fixture(scope="module")
def admin_client():
    with opshub_client(TEST_DB, role="admin") as test_client:
        yield test_client


@pytest.fixture()
def as_role():
    from cbc.shared.config import settings
    from pymongo import MongoClient

    raw = mongo_client(serverSelectionTimeoutMS=5000)

    def set_role(role: str) -> None:
        raw[TEST_DB]["users"].update_one({"email": TEST_ACTOR}, {"$set": {"role": role}})

    try:
        yield set_role
    finally:
        set_role("admin")
        raw.close()


def test_get_margins_returns_bands_and_effective(admin_client) -> None:
    response = admin_client.get("/api/reference/margins")
    assert response.status_code == 200
    body = response.json()
    assert body["bands"]
    assert "effective" in body


def test_admin_can_edit_band(admin_client) -> None:
    response = admin_client.patch("/api/reference/margins", json={"bands": {"commodity": 0.31}})
    assert response.status_code == 200
    assert response.json()["effective"]["commodity"] == 0.31


def test_estimator_cannot_edit(admin_client, as_role) -> None:
    as_role("estimator")
    response = admin_client.patch("/api/reference/margins", json={"bands": {"commodity": 0.31}})
    assert response.status_code == 403


def test_rejects_out_of_range(admin_client) -> None:
    response = admin_client.patch("/api/reference/margins", json={"bands": {"commodity": 2}})
    assert response.status_code == 422


def test_rejects_unknown_band(admin_client) -> None:
    response = admin_client.patch("/api/reference/margins", json={"bands": {"nope": 0.3}})
    assert response.status_code == 422


def test_get_tax_returns_rates(admin_client) -> None:
    response = admin_client.get("/api/reference/tax")
    assert response.status_code == 200
    assert response.json()["rates"]["OH"] == 0.08


def test_admin_can_edit_tax(admin_client) -> None:
    response = admin_client.patch("/api/reference/tax", json={"rates": {"OH": 0.0825}})
    assert response.status_code == 200
    assert response.json()["rates"]["OH"] == 0.0825


def test_admin_can_add_and_remove_jurisdiction(admin_client) -> None:
    added = admin_client.patch("/api/reference/tax", json={"rates": {"IN": 0.07}})
    assert added.json()["rates"]["IN"] == 0.07
    removed = admin_client.patch("/api/reference/tax", json={"remove": ["IN"]})
    assert "IN" not in removed.json()["rates"]


def test_estimator_cannot_edit_tax(admin_client, as_role) -> None:
    as_role("estimator")
    response = admin_client.patch("/api/reference/tax", json={"rates": {"OH": 0.09}})
    assert response.status_code == 403


def test_rejects_out_of_range_tax(admin_client) -> None:
    response = admin_client.patch("/api/reference/tax", json={"rates": {"OH": 2}})
    assert response.status_code == 422


def test_get_adders_returns_items(admin_client) -> None:
    response = admin_client.get("/api/reference/adders")
    assert response.status_code == 200
    assert "hagerListAdders" in response.json()


def test_admin_can_edit_adder(admin_client) -> None:
    response = admin_client.patch("/api/reference/adders", json={"items": {"Lead lined": 225.0}})
    assert response.status_code == 200
    items = {i["name"]: i["list_adder"] for i in response.json()["hagerListAdders"]["items"]}
    assert items["Lead lined"] == 225.0


def test_adder_rejects_negative(admin_client) -> None:
    response = admin_client.patch("/api/reference/adders", json={"items": {"Lead lined": -1}})
    assert response.status_code == 422


def test_estimator_cannot_edit_adders(admin_client, as_role) -> None:
    as_role("estimator")
    response = admin_client.patch("/api/reference/adders", json={"items": {"Lead lined": 1}})
    assert response.status_code == 403


def test_get_special_margins_lists_customers(admin_client) -> None:
    response = admin_client.get("/api/reference/special-margins")
    assert response.status_code == 200
    assert any(c["name"] == "Wendys" for c in response.json()["customers"])


def test_admin_can_set_special_margin(admin_client) -> None:
    response = admin_client.patch(
        "/api/reference/special-margins", json={"customers": [{"name": "Wendys", "margin": 0.3}]}
    )
    assert response.status_code == 200
    row = next(c for c in response.json()["customers"] if c["name"] == "Wendys")
    assert row["margin"] == 0.3


def test_special_margin_rejects_out_of_range(admin_client) -> None:
    response = admin_client.patch(
        "/api/reference/special-margins", json={"customers": [{"name": "Wendys", "margin": 2}]}
    )
    assert response.status_code == 422


def test_estimator_cannot_edit_special_margins(admin_client, as_role) -> None:
    as_role("estimator")
    response = admin_client.patch(
        "/api/reference/special-margins", json={"customers": [{"name": "Wendys", "margin": 0.3}]}
    )
    assert response.status_code == 403


def test_get_finishes(admin_client) -> None:
    response = admin_client.get("/api/reference/finishes")
    assert response.status_code == 200
    assert any(f["us_code"] == "US26D" for f in response.json()["finishes"])


def test_admin_can_edit_finish(admin_client) -> None:
    response = admin_client.patch(
        "/api/reference/finishes", json={"finishes": [{"us_code": "US26D", "description": "Edited"}]}
    )
    assert response.status_code == 200
    row = next(f for f in response.json()["finishes"] if f["us_code"] == "US26D")
    assert row["description"] == "Edited"


def test_estimator_cannot_edit_finishes(admin_client, as_role) -> None:
    as_role("estimator")
    response = admin_client.patch(
        "/api/reference/finishes", json={"finishes": [{"us_code": "US26D", "description": "x"}]}
    )
    assert response.status_code == 403


def test_get_frame_depths(admin_client) -> None:
    response = admin_client.get("/api/reference/frame-depths")
    assert response.status_code == 200
    assert any(w["type"] == "masonry" for w in response.json()["wall_types"])


def test_admin_can_edit_frame_depth(admin_client) -> None:
    response = admin_client.patch(
        "/api/reference/frame-depths", json={"wall_types": [{"type": "masonry", "depth": "6-1/4"}]}
    )
    assert response.status_code == 200
    row = next(w for w in response.json()["wall_types"] if w["type"] == "masonry")
    assert row["depth_inches"] == 6.25


def test_frame_depth_rejects_unparseable(admin_client) -> None:
    response = admin_client.patch(
        "/api/reference/frame-depths", json={"wall_types": [{"type": "masonry", "depth": "thick"}]}
    )
    assert response.status_code == 422


def test_get_frp_constants(admin_client) -> None:
    response = admin_client.get("/api/reference/frp-constants")
    assert response.status_code == 200
    assert "status" in response.json()


def test_admin_can_set_frp_constant(admin_client) -> None:
    response = admin_client.patch("/api/reference/frp-constants", json={"waste_pct": 12})
    assert response.status_code == 200
    assert response.json()["waste_pct"] == 12


def test_frp_rejects_negative(admin_client) -> None:
    response = admin_client.patch("/api/reference/frp-constants", json={"waste_pct": -1})
    assert response.status_code == 422


def test_estimator_cannot_edit_frp(admin_client, as_role) -> None:
    as_role("estimator")
    response = admin_client.patch("/api/reference/frp-constants", json={"waste_pct": 12})
    assert response.status_code == 403


def test_get_vendor_tiers(admin_client) -> None:
    response = admin_client.get("/api/reference/vendor-tiers")
    assert response.status_code == 200
    assert any(v.get("key") == "hager" for v in response.json().get("vendors", []))
