"""FR-13: an estimator's correction becomes a measurable fact.

Nothing captured any. Edits landed in `auditLog`, which answers a different
question - it records that a field changed, where improving a matcher needs to
know what the copilot proposed, what the estimator chose instead, and how
confident the copilot was while being wrong. `runmetrics.py` carried an unfilled
`"estimatorCorrections": None` where this was meant to go.
"""
from __future__ import annotations

import asyncio

import pytest

from cbc.shared.persistence import names
from cbc.modules.extraction.api import feedback
from tests.shared import mongo_client

TEST_DB = "cbc_opshub_test_feedback"


@pytest.fixture()
def events():
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings

    raw = mongo_client()
    try:
        raw.server_info()
    except Exception:
        pytest.skip("MongoDB is not running - `docker compose up -d mongo`")

    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    db_module._client = None
    raw.drop_database(TEST_DB)
    try:
        yield raw[TEST_DB][names.FEEDBACK_EVENTS]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        db_module._client = None


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


def test_a_correction_keeps_both_sides_and_the_confidence(events) -> None:
    run(feedback.record(
        bid_request_id="b1", event_type="matchCorrected", actor="kevin@cbc.com",
        field="part", proposed="1191", corrected="1279", confidence=0.82,
        reason="wrong backset",
    ))

    row = events.find_one({})
    assert row["proposedValue"]["value"] == "1191"
    assert row["correctedValue"]["value"] == "1279"
    assert row["matchConfidenceAtTime"] == 0.82, "what it claimed while being wrong"
    assert row["appliedToLearning"] is False
    assert row["userId"] == "kevin@cbc.com"


def test_one_edit_of_two_fields_is_two_lessons(events) -> None:
    """Collapsing them would make the improvement metric meaningless."""
    run(feedback.record_edits(
        bid_request_id="b1",
        changes={"cost": 74.0, "fireRating": "90"},
        before={"cost": 68.0, "fireRating": None, "confidence": 0.55},
        actor="kevin@cbc.com",
        estimate_line_id="l1",
    ))

    kinds = sorted(row["eventType"] for row in events.find({}))
    assert kinds == ["costOverridden", "extractionCorrected"]


def test_an_edit_that_is_not_a_correction_records_nothing(events) -> None:
    """Renaming a line teaches the matcher nothing."""
    run(feedback.record_edits(
        bid_request_id="b1", changes={"description": "tidier wording"},
        before={"description": "old"}, actor="kevin@cbc.com",
    ))
    assert events.count_documents({}) == 0


def test_the_proposed_value_is_the_copilots_not_the_correction(events) -> None:
    run(feedback.record_edits(
        bid_request_id="b1", changes={"margin": 0.15},
        before={"margin": 0.27, "confidence": 0.9}, actor="kevin@cbc.com",
    ))
    row = events.find_one({})
    assert row["proposedValue"]["value"] == 0.27
    assert row["correctedValue"]["value"] == 0.15


def test_recording_never_breaks_the_edit_that_produced_it(monkeypatch) -> None:
    """An estimator fixing a rating at 4pm does not care about the learning
    pipeline. The correction is already committed and audited."""
    class Broken:
        async def insert_one(self, *_args, **_kwargs):
            raise RuntimeError("mongo is having a day")

    monkeypatch.setattr(feedback, "feedback_events", lambda: Broken())
    run(feedback.record(bid_request_id="b1", event_type="lineAdded"))  # must not raise


def test_an_extraction_fix_points_at_the_opening(events) -> None:
    run(feedback.record(
        bid_request_id="b1", event_type="extractionCorrected", opening_id="o1",
        field="fireRating", proposed=None, corrected="90",
    ))
    row = events.find_one({})
    assert row["openingId"] == "o1"
    assert row["estimateLineId"] is None
