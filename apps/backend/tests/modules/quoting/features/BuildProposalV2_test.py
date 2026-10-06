"""build_proposal in code (v2): the proposal screen's own document, filed with its
review pack - against a throwaway Mongo, no model and no Claude pass."""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest
from bson import ObjectId

from cbc.shared.config import settings
from cbc.shared.persistence import names
from tests.shared import FIXTURES, mongo_client

TEST_DB = "cbc_test_build_proposal_v2"
SLUG = "proposal_v2_fixture"


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


async def _true(*_args, **_kwargs) -> bool:
    return True


@pytest.fixture()
def bid(monkeypatch):
    from cbc.modules.quoting.features import BuildProposal
    from cbc.shared import mongo as db_module

    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw.server_info()
    except Exception as exc:
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but MongoDB is not reachable: {exc}")
        pytest.skip("MongoDB is not running")
    previous_db, settings.mongodb_db = settings.mongodb_db, TEST_DB
    previous_root = settings.storage_root
    scratch = FIXTURES / "scratch" / TEST_DB
    shutil.rmtree(scratch, ignore_errors=True)
    settings.storage_root = scratch
    monkeypatch.setenv("STORAGE_ROOT", str(scratch))
    raw.drop_database(TEST_DB)
    db_module._client = None
    db = raw[TEST_DB]

    project = {"_id": ObjectId(), "slug": SLUG, "code": "PV-001", "name": "Proposal fixture", "state": "OH",
               "gc": "Turner", "initiator": "Kellan Smith"}
    db[names.BID_REQUESTS].insert_one(dict(project))
    db[names.OPENINGS].insert_many([
        {"projectId": project["_id"], "mark": mark, "hwSet": "01", "inScope": True, "status": "clear",
         "fireRating": "90 MIN"} for mark in ("101", "102")
    ] + [{"projectId": project["_id"], "mark": "100A", "inScope": False, "status": "clear",
          "scopeReason": "aluminum storefront, by others"}])
    common = {"projectId": project["_id"], "addedByHand": False, "marginOverridden": False, "flags": []}
    db[names.ESTIMATE_LINES].insert_many([
        {**common, "lineKey": "1:01", "part": "3553", "manufacturer": "Hager", "description": "ENTRY LOCK",
         "division": "08 71 00", "group": "01", "qty": 2, "cost": 74.0, "openings": ["101", "102"],
         "qtyPerOpening": 1, "costSource": "LIST_X_MULTIPLIER"},
        {**common, "lineKey": "1:02", "part": "5200", "manufacturer": "Hager", "description": "CLOSER",
         "division": "08 71 00", "group": "01", "qty": 2, "cost": None, "openings": ["101", "102"],
         "alternateGroup": "Supplied by others", "notes": "supplied by the landlord per the legend"},
    ])
    monkeypatch.setattr(BuildProposal.ops_jobs, "holds_lease", _true)
    try:
        yield project, db, scratch / SLUG
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db, settings.storage_root = previous_db, previous_root
        shutil.rmtree(scratch, ignore_errors=True)
        db_module._client = None


def test_the_proposal_is_built_in_code_from_the_quote_as_it_stands(bid) -> None:
    from cbc.modules.quoting.features import BuildProposal

    project, db, root = bid
    job = {"_id": ObjectId(), "type": "build_proposal", "projectId": project["_id"]}

    note = run(BuildProposal.build_in_code(job, project))

    html = (root / "quotation.html").read_text(encoding="utf-8")
    assert "Hardware set 01" in html and "doors 101, 102" in html and "90 MIN fire rated" in html
    assert "$202.74" in html  # 74.00 at the commodity band, 27%: 101.37 x 2
    assert "Not included - the documents assign these to others: CLOSER" in html
    assert "aluminum storefront, by others: door 100A" in html
    email = (root / "review" / "quotation_email_draft.md").read_text(encoding="utf-8")
    assert email.startswith("# Quotation Email - DRAFT") and "Hi Kellan," in email
    assert (root / "review" / "review_flags.json").is_file()
    stored = db[names.PROPOSALS].find_one({"projectId": project["_id"]})
    assert stored["claudeArtifacts"]["quotationHtml"] and stored["claudeArtifacts"]["emailDraft"]
    assert note.startswith("proposal built in code")


def test_the_proposal_job_runs_in_code_when_the_switch_says_so(monkeypatch) -> None:
    from cbc.modules.quoting.features import BuildProposal

    seen: dict = {}

    async def run_pass(job, **kwargs):
        seen.update(kwargs)

    async def engine() -> str:
        return "v2"

    monkeypatch.setattr(BuildProposal.ops_pipeline, "proposal_engine", engine)
    monkeypatch.setattr(BuildProposal.pipeline, "run_pass", run_pass)
    asyncio.run(BuildProposal.run({"_id": ObjectId(), "type": "build_proposal"}))

    assert seen["work"] is BuildProposal.build_in_code and "prepare" not in seen
