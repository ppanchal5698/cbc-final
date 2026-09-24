"""What a pass wrote on disk, landing in MongoDB.

This is the seam between the two actors - Claude writes JSON, the worker syncs it -
and it had no tests. Every failure here is silent by construction: a shape the
importer does not recognise produces zero openings and a clean "done", and the
estimator sees an empty bid rather than an error.

Frozen artifacts, no Claude. The point is the importer, not the extraction.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from pymongo import MongoClient

from cbc.shared.config import settings
from tests.shared import FIXTURES, ROOT, mongo_client
from cbc.shared.persistence import names

TEST_DB = "cbc_test_sync_import"
SLUG = "sync_import_fixture"


def run(coro):
    """Each test gets its own loop, so the motor client binds to it."""
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


@pytest.fixture()
def project():
    """A throwaway database and an isolated projects/ root, with one bid in it."""
    from cbc.shared import mongo as db_module

    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw.server_info()
    except Exception as exc:
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but MongoDB is not reachable: {exc}")
        pytest.skip("MongoDB is not running - start it with `docker compose up -d mongo`")

    previous_db, settings.mongodb_db = settings.mongodb_db, TEST_DB
    previous_root = settings.storage_root
    scratch = FIXTURES / "scratch" / TEST_DB
    shutil.rmtree(scratch, ignore_errors=True)
    settings.storage_root = scratch
    raw.drop_database(TEST_DB)
    db_module._client = None

    record = {"_id": ObjectId(), "slug": SLUG, "code": "SY-001", "name": "Sync fixture"}
    raw[TEST_DB][names.BID_REQUESTS].insert_one(dict(record))

    try:
        yield record, raw[TEST_DB], scratch / SLUG
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous_db
        settings.storage_root = previous_root
        shutil.rmtree(scratch, ignore_errors=True)
        db_module._client = None


def _write(directory, relative, payload):
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _opening(number: str, **overrides):
    base = {
        "door_number": number,
        "size": "3070",
        "handing": "LH",
        "finish": "US26D",
        "fire_rating": "90",
        "source_page": 14,
        "source_file": "bid.pdf",
        "page_size": {"width": 612, "height": 792},
        "bbox": [72, 300, 320, 316],
        "confidence": 0.92,
    }
    base.update(overrides)
    return base


# ── extraction ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param(lambda rows: rows, id="bare-array"),
        pytest.param(lambda rows: {"openings": rows}, id="openings-wrapper"),
        pytest.param(lambda rows: {"lines": rows}, id="lines-wrapper"),
    ],
)
def test_every_shape_a_pass_has_written_is_imported(project, shape) -> None:
    """Three shapes have come out of real runs. All three must import.

    A shape the importer does not recognise yields zero openings and reports
    success, which is the worst available outcome: the bid looks empty rather
    than broken.
    """
    from cbc.modules.extraction.api import line_items

    record, database, directory = project
    _write(directory, "extracted/line_items.json", shape([_opening("101"), _opening("102")]))

    counts = run(line_items.import_extraction(record))

    assert counts["inserted"] == 2, counts
    assert database[names.OPENINGS].count_documents({"projectId": record["_id"]}) == 2


def test_importing_twice_updates_rather_than_duplicates(project) -> None:
    """A rerun must not double the schedule."""
    from cbc.modules.extraction.api import line_items

    record, database, directory = project
    _write(directory, "extracted/line_items.json", {"openings": [_opening("101")]})
    run(line_items.import_extraction(record))

    _write(
        directory,
        "extracted/line_items.json",
        {"openings": [_opening("101", finish="US32D")]},
    )
    second = run(line_items.import_extraction(record))

    assert database[names.OPENINGS].count_documents({"projectId": record["_id"]}) == 1
    assert second["inserted"] == 0
    stored = database[names.OPENINGS].find_one({"projectId": record["_id"]})
    assert stored["finish"] == "US32D (630)", "a rerun must carry the correction through (NR-3)"


def test_import_normalizes_finish_and_maps_alternate(project) -> None:
    """FR-2 alternate designation and NR-3 finish pair land on the line item."""
    from cbc.modules.extraction.api import line_items

    record, database, directory = project
    _write(
        directory,
        "extracted/line_items.json",
        {
            "openings": [
                _opening(
                    "101",
                    finish="626",
                    alternate="Alternate 1",
                    flags=["handing_missing"],
                )
            ]
        },
    )

    run(line_items.import_extraction(record))
    stored = database[names.OPENINGS].find_one({"projectId": record["_id"]})
    assert stored["finish"] == "US26D (626)"
    assert stored["alternateGroup"] == "Alternate 1"
    assert "handing_missing" in stored["flags"]


def test_import_flags_ambiguous_finish_without_guessing(project) -> None:
    from cbc.modules.extraction.api import line_items

    record, database, directory = project
    _write(
        directory,
        "extracted/line_items.json",
        {"openings": [_opening("101", finish="619")]},
    )

    run(line_items.import_extraction(record))
    stored = database[names.OPENINGS].find_one({"projectId": record["_id"]})
    assert stored["finish"] == "619"
    assert "finish_ambiguous" in stored["flags"]


def test_scope_metadata_lands_on_the_project(project) -> None:
    from cbc.modules.projects.api import scope_metadata

    record, database, directory = project
    _write(
        directory,
        "extracted/scope_metadata.json",
        {"project_name": "Dutch Bros MacArthur", "state": "OH", "architect": "HDA"},
    )

    assert run(scope_metadata.import_scope_metadata(record)) is True
    stored = database[names.BID_REQUESTS].find_one({"_id": record["_id"]})
    assert stored.get("state") == "OH"


def test_scope_metadata_maps_bid_due_to_bidDue(project) -> None:
    """Agent bid_due_date must land on project.bidDue — never bidDueDate."""
    from cbc.modules.projects.api import scope_metadata

    record, database, directory = project
    _write(
        directory,
        "extracted/scope_metadata.json",
        {"bid_due_date": "2026-09-15", "mode": "templated", "bid_alternates": ["Alternate 1"]},
    )

    assert run(scope_metadata.import_scope_metadata(record)) is True
    stored = database[names.BID_REQUESTS].find_one({"_id": record["_id"]})
    bid_due = stored.get("bidDue")
    assert getattr(bid_due, "isoformat", lambda: bid_due)()[:10] == "2026-09-15" or str(bid_due)[:10] == "2026-09-15"
    assert "bidDueDate" not in stored
    assert stored.get("mode") == "templated"
    assert stored.get("bidAlternates") == ["Alternate 1"]


def test_scope_metadata_does_not_clobber_ops_hub_mode(project) -> None:
    from cbc.modules.projects.api import scope_metadata

    record, database, directory = project
    database[names.BID_REQUESTS].update_one(
        {"_id": record["_id"]},
        {"$set": {"mode": "one_off", "initiator": "Rebecca", "bidAlternates": ["Alt A"]}},
    )
    record["mode"] = "one_off"
    record["initiator"] = "Rebecca"
    record["bidAlternates"] = ["Alt A"]

    _write(
        directory,
        "extracted/scope_metadata.json",
        {
            "mode": "templated",
            "initiator": "Kellan",
            "bid_alternates": ["Alt A", "Alternate 2"],
        },
    )

    assert run(scope_metadata.import_scope_metadata(record)) is True
    stored = database[names.BID_REQUESTS].find_one({"_id": record["_id"]})
    assert stored.get("mode") == "one_off"
    assert stored.get("initiator") == "Rebecca"
    assert stored.get("bidAlternates") == ["Alt A", "Alternate 2"]


def test_scope_metadata_fills_empties_with_provenance(project) -> None:
    """Create-form gaps get PDF values + intakeFieldSources; Ops-Hub due date stays."""
    from datetime import datetime, timezone

    from cbc.modules.projects.api import scope_metadata

    record, database, directory = project
    due = datetime(2026, 9, 20, tzinfo=timezone.utc)
    database[names.BID_REQUESTS].update_one(
        {"_id": record["_id"]},
        {"$set": {"bidDue": due, "name": "Phone-in placeholder"}},
    )
    record["bidDue"] = due
    record["name"] = "Phone-in placeholder"

    _write(
        directory,
        "extracted/scope_metadata.json",
        {
            "brand": "Dutch Bros Coffee",
            "city": "Alexandria",
            "state": "la",
            "architect": "Coralic LLC",
            "bid_due_date": "2026-01-01",
            "source_page": 1,
            "source_files": ["uploads/raw/arch.pdf"],
            "field_sources": {
                "brand": {
                    "source_file": "uploads/raw/arch.pdf",
                    "source_page": 1,
                    "excerpt": "Dutch Bros Coffee",
                },
                "architect": {
                    "source_file": "uploads/raw/arch.pdf",
                    "source_page": 2,
                    "excerpt": "ARCHITECT: Coralic LLC",
                },
            },
        },
    )

    assert run(scope_metadata.import_scope_metadata(record)) is True
    stored = database[names.BID_REQUESTS].find_one({"_id": record["_id"]})
    assert stored.get("brand") == "Dutch Bros Coffee"
    assert stored.get("state") == "LA"
    assert stored.get("location") == "Alexandria, LA"
    assert stored.get("architect") == "Coralic LLC"
    stored_due = stored.get("bidDue")
    assert stored_due.year == 2026 and stored_due.month == 9 and stored_due.day == 20
    assert stored.get("name") == "Phone-in placeholder"
    sources = stored.get("intakeFieldSources") or {}
    assert sources["brand"]["sourcePage"] == 1
    assert sources["brand"]["excerpt"] == "Dutch Bros Coffee"
    assert sources["architect"]["sourcePage"] == 2
    assert sources["location"]["fromPdf"] is True
    assert "bidDue" not in sources


def test_scope_metadata_imports_without_door_schedule(project) -> None:
    """Finishes-only / early checkpoint still updates the job record."""
    from cbc.modules.extraction.api import line_items

    record, database, directory = project
    _write(
        directory,
        "extracted/scope_metadata.json",
        {"brand": "BK", "state": "OH", "source_page": 3},
    )

    counts = run(line_items.import_extraction(record))
    assert counts == {"inserted": 0, "updated": 0, "skipped": 0}
    stored = database[names.BID_REQUESTS].find_one({"_id": record["_id"]})
    assert stored.get("brand") == "BK"
    assert stored.get("state") == "OH"
    assert stored.get("intakeFieldSources", {}).get("brand", {}).get("sourcePage") == 3


# ── pricing ─────────────────────────────────────────────────────────────────


def _line(line_id: str, **overrides):
    base = {
        "line_id": line_id,
        "group": "Door 101",
        "group_type": "door",
        "part_number": "3400",
        "description": "Hager 3400 lockset",
        "division": "08 71 00",
        "quantity": 2,
        "cost": 100.0,
        "margin": 0.27,
        "sale_ea": 136.99,
        "ext_price": 273.98,
        "cost_source": "LIST_X_MULTIPLIER",
        "cost_source_detail": "hager_price_book_18.pdf PDF p42",
        "source_page": 14,
        "flags": [],
    }
    base.update(overrides)
    return base


def test_priced_lines_are_imported(project) -> None:
    from cbc.modules.quoting.api import priced_lines

    record, database, directory = project
    _write(directory, "priced/line_items.json", {"lines": [_line("L1"), _line("L2")]})

    counts = run(priced_lines.import_quote_lines(record))

    assert counts["inserted"] == 2, counts
    assert database[names.ESTIMATE_LINES].count_documents({"projectId": record["_id"]}) == 2


def test_a_manual_line_keeps_a_null_cost(project) -> None:
    """NR-13. A number here would be an invented price that looks finished."""
    from cbc.modules.quoting.api import priced_lines

    record, database, directory = project
    _write(
        directory,
        "priced/line_items.json",
        {"lines": [_line("L1", cost=None, sale_ea=None, ext_price=None,
                          cost_source="MANUAL",
                          cost_source_detail="9ft leaf - custom size, no catalog price")]},
    )
    run(priced_lines.import_quote_lines(record))

    stored = database[names.ESTIMATE_LINES].find_one({"projectId": record["_id"]})
    assert stored["cost"] is None
    assert stored["costSource"] == "MANUAL"


def test_a_negative_cost_is_flagged_rather_than_stored(project) -> None:
    """The schema bounds what an estimator types; a run writes straight through."""
    from cbc.modules.quoting.api import priced_lines

    record, database, directory = project
    _write(directory, "priced/line_items.json", {"lines": [_line("L1", cost=-45)]})
    run(priced_lines.import_quote_lines(record))

    stored = database[names.ESTIMATE_LINES].find_one({"projectId": record["_id"]})
    assert stored["cost"] is None
    assert any("negative" in flag for flag in stored.get("flags", []))


# ── proposal ────────────────────────────────────────────────────────────────


def test_proposal_artifacts_are_recorded_when_present(project) -> None:
    from cbc.modules.quoting.api import proposal_artifacts

    record, _database, directory = project
    (directory).mkdir(parents=True, exist_ok=True)
    (directory / "quotation.html").write_text("<html>quote</html>", encoding="utf-8")
    _write(directory, "review/review_flags.json", [])

    written = run(proposal_artifacts.import_proposal_artifacts(record))

    assert written["quotationHtml"] is True
    assert written["reviewFlags"] is True


def test_a_missing_artifact_is_reported_as_missing(project) -> None:
    """Not an exception, and not silently true - the proposal screen reads this."""
    from cbc.modules.quoting.api import proposal_artifacts

    record, _database, _directory = project
    written = run(proposal_artifacts.import_proposal_artifacts(record))
    assert all(present is False for present in written.values()), written


# ── nothing on disk ─────────────────────────────────────────────────────────


def test_an_absent_schedule_imports_nothing_and_does_not_raise(project) -> None:
    """A pass that wrote no schedule is a failed pass, and the gate reports it.

    The importer's job is to be honest about finding nothing, not to invent an
    error the validation layer already raises with a better message.
    """
    from cbc.modules.extraction.api import line_items

    record, database, _directory = project
    counts = run(line_items.import_extraction(record))

    assert counts["inserted"] == 0
    assert database[names.OPENINGS].count_documents({"projectId": record["_id"]}) == 0


def test_malformed_price_is_rejected_before_import(project) -> None:
    from cbc.modules.extraction.api.validation.artifacts import ArtifactValidationError
    from cbc.modules.extraction.api.validation.contracts import raise_if_invalid

    record, database, directory = project
    _write(
        directory,
        "priced/line_items.json",
        [
            {
                "line_id": "L1",
                "group": "Door 101",
                "group_type": "door",
                "quantity": 1,
                "cost_source": "MANUAL",
                "cost": "twelve dollars",
            }
        ],
    )
    try:
        raise_if_invalid("match_and_price", record["slug"])
        raise AssertionError("malformed cost should fail the contract gate")
    except ArtifactValidationError as exc:
        assert exc.quarantine
        assert "cost" in str(exc).lower() or "number" in str(exc).lower()
    assert database[names.ESTIMATE_LINES].count_documents({}) == 0


def test_numeric_price_string_is_coerced(project) -> None:
    from cbc.modules.extraction.api.validation.contracts import raise_if_invalid

    _record, _database, directory = project
    _write(
        directory,
        "priced/line_items.json",
        [
            {
                "line_id": "L1",
                "group": "Door 101",
                "group_type": "door",
                "quantity": "2",
                "cost_source": "MANUAL",
                "cost": "12.50",
            }
        ],
    )
    raise_if_invalid("match_and_price", _record["slug"])


def test_a_reimport_over_a_confirmed_row_refreshes_its_evidence(project) -> None:
    """The estimator's values stay; the provenance is brought up to date.

    That branch reached for a variable the import loop no longer held, so the
    path every confirmed bid takes on its next run raised NameError. The suite
    never noticed, because nothing imported over a confirmed row.
    """
    from cbc.modules.extraction.api import line_items

    record, database, directory = project
    _write(directory, "extracted/line_items.json", {"openings": [_opening("101")]})
    run(line_items.import_extraction(record))

    database[names.OPENINGS].update_one(
        {"projectId": record["_id"]},
        {"$set": {
            "confirmedAt": datetime.now(timezone.utc),
            "confirmedBy": "kevin@cbc.com",
            "finish": "US10B",
        }},
    )

    moved = _opening("101")
    moved["source_page"] = 44
    moved["raw_row"] = "101 | re-read from a later sheet"
    _write(directory, "extracted/line_items.json", {"openings": [moved]})
    run(line_items.import_extraction(record))

    stored = database[names.OPENINGS].find_one({"projectId": record["_id"]})
    assert stored["finish"] == "US10B", "a confirmed value is the estimator's"
    assert stored["evidence"]["sourcePage"] == 44, "but its provenance follows the re-read"
