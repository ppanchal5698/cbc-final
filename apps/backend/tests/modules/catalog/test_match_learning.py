"""FR-13 end to end: a correction an estimator makes teaches the next bid.

`feedbackEvents` captured corrections from the day it was written, behind a
partial index built for draining them - and nothing ever drained it. The system
test said so outright: *"nothing has consumed it yet"*. These are the tests for
the consumer.
"""
from __future__ import annotations

import asyncio

import pytest

from cbc.modules.catalog.api import learning
from cbc.modules.catalog.domain import partquery
from cbc.modules.extraction.api import feedback
from cbc.shared.persistence import names
from tests.shared import mongo_client, require_mongo

TEST_DB = "cbc_opshub_test_learning"

PEMKO = {
    "part": "275A",
    "manufacturer": "Pemko",
    "vendorKey": "pemko",
    "description": "275A",
    "division": "08 71 00",
    "cost": 7.16,
    "seedSource": "catalog.md + catalogs/ 2026 baseline",
}
RATED_DOOR = {
    "part": "HM-90",
    "manufacturer": "Hager",
    "vendorKey": "hager",
    "description": "90 minute rated hollow metal door",
    "division": "08 11 00",
    "cost": 410.0,
    "seedSource": "catalog.md + catalogs/ 2026 baseline",
}


@pytest.fixture()
def db():
    from cbc.shared import mongo as db_module
    from cbc.shared.config import settings

    raw = mongo_client()
    require_mongo(raw)

    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    db_module._client = None
    raw.drop_database(TEST_DB)
    try:
        yield raw[TEST_DB]
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


def _seed_part(db, row: dict) -> object:
    return db[names.CATALOG_ITEMS].insert_one(dict(row)).inserted_id


def test_a_correction_becomes_something_the_next_bid_can_recall(db) -> None:
    item_id = _seed_part(db, PEMKO)

    run(
        feedback.record(
            bid_request_id="b1",
            event_type="matchCorrected",
            actor="kevin@cbc.com",
            field="part",
            proposed="NGP 431S",
            corrected="275A",
            confidence=0.55,
            reason="Pemko, not the NGP comparison number",
            corrected_catalog_item_id=str(item_id),
            spec="Threshold, PEMKO 275A, 42 inches",
        )
    )

    result = run(feedback.apply_to_learning())
    assert result["learned"] == 1, result

    learned = db[names.MATCH_LEARNING].find_one({})
    assert learned["part"] == "275A"
    assert learned["confirmCount"] == 1
    assert learned["rejectCount"] == 0
    assert learned["lastConfirmedBy"] == "kevin@cbc.com"
    assert learned["specKey"] == partquery.spec_key("Threshold, PEMKO 275A, 42 inches")

    # And the queue is now drained, which is the flag nothing used to flip.
    assert db[names.FEEDBACK_EVENTS].find_one({})["appliedToLearning"] is True

    recalled = run(learning.recall("threshold, pemko 275a, 42 INCHES"))
    assert len(recalled) == 1, "case and separators must not hide a learned answer"
    assert recalled[0]["part"] == "275A"


def test_draining_twice_does_not_count_the_same_lesson_twice(db) -> None:
    item_id = _seed_part(db, PEMKO)
    run(
        feedback.record(
            bid_request_id="b1",
            event_type="matchCorrected",
            actor="kevin@cbc.com",
            corrected_catalog_item_id=str(item_id),
            spec="PEMKO 275A threshold",
        )
    )

    assert run(feedback.apply_to_learning())["learned"] == 1
    second = run(feedback.apply_to_learning())
    assert second["read"] == 0, "the second drain must find an empty queue"
    assert db[names.MATCH_LEARNING].find_one({})["confirmCount"] == 1


def test_two_estimators_confirming_the_same_spec_raise_its_confidence(db) -> None:
    item_id = _seed_part(db, PEMKO)
    for actor in ("kevin@cbc.com", "rick@cbc.com"):
        run(
            feedback.record(
                bid_request_id="b1",
                event_type="matchCorrected",
                actor=actor,
                corrected_catalog_item_id=str(item_id),
                spec="PEMKO 275A threshold",
            )
        )
        run(feedback.apply_to_learning())

    learned = db[names.MATCH_LEARNING].find_one({})
    assert learned["confirmCount"] == 2
    assert learned["lastConfirmedBy"] == "rick@cbc.com", "the most recent word wins"


def test_a_rejection_counts_against_the_part_it_was_proposed_for(db) -> None:
    """The 'which library items get rejected most' question §3.31 asks."""
    item_id = _seed_part(db, PEMKO)
    run(
        feedback.record(
            bid_request_id="b1",
            event_type="matchRejected",
            actor="kevin@cbc.com",
            proposed="275A",
            proposed_catalog_item_id=str(item_id),
            spec="Threshold, 42 inches, aluminium",
            reason="wrong profile",
        )
    )

    assert run(feedback.apply_to_learning())["rejected"] == 1
    learned = db[names.MATCH_LEARNING].find_one({})
    assert learned["rejectCount"] == 1
    assert learned.get("confirmCount", 0) == 0
    assert "lastConfirmedAt" not in learned, "a rejection confirms nothing"


def test_a_correction_naming_no_catalog_row_is_drained_not_replayed(db) -> None:
    """Allegion is not in the catalog. That event will never resolve - flip it anyway."""
    run(
        feedback.record(
            bid_request_id="b1",
            event_type="matchCorrected",
            actor="kevin@cbc.com",
            corrected="VON-DUPRIN-99EO-42-626",
            spec="Exit device, Von Duprin 99EO",
        )
    )

    result = run(feedback.apply_to_learning())
    assert result["skipped"] == 1 and result["learned"] == 0
    assert db[names.MATCH_LEARNING].count_documents({}) == 0
    assert db[names.FEEDBACK_EVENTS].find_one({})["appliedToLearning"] is True


def test_a_margin_override_teaches_the_matcher_nothing(db) -> None:
    """It is a commercial decision about a match that was already right."""
    _seed_part(db, PEMKO)
    run(
        feedback.record(
            bid_request_id="b1",
            event_type="marginOverridden",
            actor="kevin@cbc.com",
            field="margin",
            proposed=0.30,
            corrected=0.22,
            spec="PEMKO 275A threshold",
        )
    )

    assert run(feedback.apply_to_learning())["read"] == 0
    assert db[names.MATCH_LEARNING].count_documents({}) == 0
    assert db[names.FEEDBACK_EVENTS].find_one({})["appliedToLearning"] is False


def test_a_blank_specification_is_never_learned_against(db) -> None:
    """A blank key would collide with every other blank one."""
    item_id = _seed_part(db, PEMKO)
    run(
        feedback.record(
            bid_request_id="b1",
            event_type="matchCorrected",
            actor="kevin@cbc.com",
            corrected_catalog_item_id=str(item_id),
            spec="   ",
        )
    )

    assert run(feedback.apply_to_learning())["learned"] == 0
    assert db[names.MATCH_LEARNING].count_documents({}) == 0


def test_a_learned_match_is_recalled_but_a_rated_opening_still_vetoes_it(db) -> None:
    """The rule that makes the whole feature safe to turn on.

    Recall answers "what did an estimator choose for this specification". It does
    not answer "is that part legal on this opening" - fire rating, handing and
    finish do, and they outrank any number of confirmations. The tool carries
    that instruction; this pins the fact recall makes it necessary, by showing
    recall happily returning an unrated part.
    """
    unrated_id = _seed_part(db, {**PEMKO, "part": "UNRATED-DOOR", "division": "08 11 00"})
    _seed_part(db, RATED_DOOR)

    run(
        feedback.record(
            bid_request_id="b1",
            event_type="matchCorrected",
            actor="kevin@cbc.com",
            corrected_catalog_item_id=str(unrated_id),
            spec="Door 101, 3070, hollow metal",
        )
    )
    run(feedback.apply_to_learning())

    recalled = run(learning.recall("Door 101, 3070, hollow metal"))
    assert recalled and recalled[0]["part"] == "UNRATED-DOOR"
    assert "fireRating" not in recalled[0], (
        "recall carries no rating, so it can never clear a rated opening by itself - "
        "the matcher's hard constraints must still run"
    )
