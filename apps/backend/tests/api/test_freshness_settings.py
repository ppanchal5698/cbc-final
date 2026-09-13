"""Admin-editable catalog / P21 freshness windows."""
from __future__ import annotations

from pymongo import MongoClient

from cbc.shared.config import settings
from cbc.modules.ops.api import freshness as freshness_settings
from tests.shared import TEST_ACTOR, opshub_client, mongo_client
from cbc.shared.persistence import names

TEST_DB = "cbc_opshub_test_freshness"


def test_freshness_settings_ship_the_windows_the_workbook_states():
    """Price sheets ~24 months (Matrix 6.3); costs discarded at 3 years (6.2).

    The two used to be one number. This endpoint reports the price-sheet window,
    which is unchanged; the cost window moved to Matrix 6.2 and is asserted in
    tests/pipeline/test_freshness.py.
    """
    from cbc.modules.ops.api import freshness_rules as core

    with opshub_client(TEST_DB) as client:
        freshness_settings.clear_cache()
        body = client.get("/api/settings/freshness").json()
        assert body["catalogStaleMonths"] == core.CATALOG_STALE_MONTHS == 24
        assert body["discardAfterMonths"] == core.DISCARD_AFTER_MONTHS == 36
        assert body["catalogStaleDays"] == core.CATALOG_STALE_DAYS == 730
        assert body["discardAfterDays"] == core.DISCARD_AFTER_DAYS == 1095
        assert (body["freshMonths"], body["freshDays"]) == (core.FRESH_MONTHS, core.FRESH_DAYS) == (6, 183)


def test_saving_freshness_settings_round_trips():
    with opshub_client(TEST_DB) as client:
        freshness_settings.clear_cache()
        try:
            saved = client.put(
                "/api/settings/freshness",
                json={"catalogStaleMonths": 18, "discardAfterMonths": 36},
            )
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert body["catalogStaleMonths"] == 18
            assert body["discardAfterMonths"] == 36
            assert body["updatedBy"] == TEST_ACTOR

            again = client.get("/api/settings/freshness").json()
            assert again["catalogStaleMonths"] == 18
            assert again["discardAfterMonths"] == 36

            raw = mongo_client(serverSelectionTimeoutMS=5000)
            try:
                entries = list(
                    raw[TEST_DB][names.AUDIT_LOGS].find({"action": "settings.freshness.update"})
                )
            finally:
                raw.close()
            assert entries
            assert entries[-1]["after"]["catalogStaleMonths"] == 18
        finally:
            # Shared process cache must not leak 18/36 into p21 / catalog tests.
            freshness_settings.clear_cache()


def test_the_review_window_does_not_bound_the_cost_bands():
    """data-stewardship.md: the price-sheet window and the P21 bands move independently.

    Reviewing price sheets every 48 months says nothing about when a purchase-order
    cost is discarded. This save was a 422 while one setting drove both.
    """
    from cbc.modules.ops.api import freshness_rules as core

    with opshub_client(TEST_DB) as client:
        freshness_settings.clear_cache()
        try:
            saved = client.put("/api/settings/freshness", json={"catalogStaleMonths": 48, "discardAfterMonths": 36})
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert (body["catalogStaleMonths"], body["discardAfterMonths"], body["freshMonths"]) == (48, 36, 6)
            assert body["rule"] == core.rule_text(6, 36), "the rule text names the cost band, not the sheet window"

            moved = client.put(
                "/api/settings/freshness",
                json={"catalogStaleMonths": 48, "discardAfterMonths": 36, "freshMonths": 8},
            ).json()
            assert (moved["catalogStaleDays"], moved["freshDays"]) == (core.days_from_months(48), core.days_from_months(8))

            kept = client.put("/api/settings/freshness", json={"catalogStaleMonths": 12, "discardAfterMonths": 36}).json()
            assert (kept["catalogStaleMonths"], kept["freshMonths"]) == (12, 8), "a save without the fresh band keeps it"
        finally:
            freshness_settings.clear_cache()


def test_a_cost_is_discarded_only_after_it_stops_being_fresh():
    with opshub_client(TEST_DB) as client:
        freshness_settings.clear_cache()
        try:
            for body in (
                {"catalogStaleMonths": 24, "discardAfterMonths": 12, "freshMonths": 12},
                {"catalogStaleMonths": 24, "discardAfterMonths": 6},  # the stored or default 6-month band
            ):
                assert client.put("/api/settings/freshness", json=body).status_code == 422, body
        finally:
            freshness_settings.clear_cache()
