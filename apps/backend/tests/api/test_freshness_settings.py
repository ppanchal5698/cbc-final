"""Admin-editable catalog / P21 freshness windows."""
from __future__ import annotations

from pymongo import MongoClient

from cbc.shared.config import settings
from cbc.modules.ops.api import freshness as freshness_settings
from tests.shared import TEST_ACTOR, opshub_client, mongo_client
from cbc.persistence import names

TEST_DB = "cbc_opshub_test_freshness"


def test_freshness_settings_ship_the_windows_the_workbook_states():
    """Price sheets ~24 months (Matrix 6.3); costs discarded at 3 years (6.2).

    The two used to be one number. This endpoint reports the price-sheet window,
    which is unchanged; the cost window moved to Matrix 6.2 and is asserted in
    tests/pipeline/test_freshness.py.
    """
    from cbc.domain import freshness as core

    with opshub_client(TEST_DB) as client:
        freshness_settings.clear_cache()
        body = client.get("/api/settings/freshness").json()
        assert body["catalogStaleMonths"] == core.CATALOG_STALE_MONTHS == 24
        assert body["discardAfterMonths"] == core.DISCARD_AFTER_MONTHS == 36
        assert body["catalogStaleDays"] == core.CATALOG_STALE_DAYS == 730
        assert body["discardAfterDays"] == core.DISCARD_AFTER_DAYS == 1095


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


def test_discard_must_be_later_than_the_review_window():
    with opshub_client(TEST_DB) as client:
        response = client.put(
            "/api/settings/freshness",
            json={"catalogStaleMonths": 24, "discardAfterMonths": 12},
        )
        assert response.status_code == 422
