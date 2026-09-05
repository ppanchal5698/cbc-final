"""Admin-editable catalog / P21 freshness windows."""
from __future__ import annotations

from pymongo import MongoClient

from cbc.config import settings
from cbc.services import freshness as freshness_settings
from tests.shared import TEST_ACTOR, opshub_client

TEST_DB = "cbc_opshub_test_freshness"


def test_freshness_settings_default_to_twenty_four_and_thirty_months():
    with opshub_client(TEST_DB) as client:
        freshness_settings.clear_cache()
        body = client.get("/api/settings/freshness").json()
        assert body["catalogStaleMonths"] == 24
        assert body["discardAfterMonths"] == 30
        assert body["catalogStaleDays"] == 730
        assert body["discardAfterDays"] == 913


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

            raw = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
            try:
                entries = list(
                    raw[TEST_DB]["auditLog"].find({"action": "settings.freshness.update"})
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
