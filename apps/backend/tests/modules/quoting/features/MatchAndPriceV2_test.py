"""match_and_price v2 end to end: a take-off in Mongo and on disk, priced in code,
landed in estimateLines and rolled up - against a throwaway Mongo, no model."""
from __future__ import annotations

import asyncio
import json
import os
import shutil

import pytest
from bson import ObjectId

from cbc.modules.quoting.domain.questions import CatalogChoice
from cbc.shared import ai
from cbc.shared.config import settings
from cbc.shared.persistence import names
from tests.shared import FIXTURES, mongo_client

TEST_DB = "cbc_test_match_and_price_v2"
SLUG = "v2_fixture"


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


SETS = {"sets": [
    {"set_id": "01", "source_page": 16, "items": [
        {"qty": "1 1/2", "unit": "PR.", "part": "BB1279", "manufacturer": "Hager", "finish": "US26D",
         "description": 'HINGES 4 1/2" x 4 1/2"'},
        {"qty": "1", "unit": "EA.", "part": "431S", "manufacturer": "Hager", "description": 'THRESHOLD 48"'},
        {"qty": "1", "unit": "EA.", "part": "99EO", "manufacturer": "Von Duprin", "description": "EXIT DEVICE"},
        {"qty": "1", "unit": "EA.", "part": "346C", "manufacturer": "Pemko", "description": "GASKET",
         "supplied_by": "OWNER"},
        {"qty": "1", "unit": "EA.", "part": "ZZ123", "manufacturer": "Arrow", "description": "CLOSER"},
        {"qty": "1", "unit": "EA.", "part": "5100", "manufacturer": "Hager", "finish": "ALM",
         "description": "CLOSER PARALLEL ARM"},
    ]},
]}


@pytest.fixture()
def bid(monkeypatch):
    from cbc.modules.quoting.features import MatchAndPrice
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
    raw.drop_database(TEST_DB)
    db_module._client = None
    db = raw[TEST_DB]

    project = {"_id": ObjectId(), "slug": SLUG, "code": "V2-001", "name": "V2 fixture", "state": "OH"}
    db[names.BID_REQUESTS].insert_one(dict(project))
    db[names.OPENINGS].insert_many([
        {"projectId": project["_id"], "mark": "101", "hwSet": "GROUP 01", "inScope": True, "status": "clear",
         "fireRating": "90", "evidence": {"sourcePage": 12, "sourceFile": "A601.pdf"}},
        {"projectId": project["_id"], "mark": "102", "hwSet": "SET 1", "inScope": True, "status": "clear",
         "evidence": {"sourcePage": 12, "sourceFile": "A601.pdf"}},
        {"projectId": project["_id"], "mark": "103", "hwSet": "GROUP 01", "inScope": False, "status": "clear"},
    ])
    seed = "catalog.md + catalogs/ 2026 baseline"
    db[names.CATALOG_ITEMS].insert_many([
        {"part": "346C", "manufacturer": "Pemko", "vendorKey": "pemko", "cost": 3.82, "listPrice": 7.96,
         "multiplier": 0.48, "seedSource": seed, "description": "346C"},
        {"part": "BB1279", "manufacturer": "Hager", "vendorKey": "hager", "cost": 1.0, "seedSource": "price book ingest"},
    ])
    book_id = ObjectId()
    db[names.PRICE_BOOKS].insert_one({"_id": book_id, "vendor": "hager", "program": "Hager Price Book #18",
                                      "effective": "2026-03-02", "entries": {"fileSha": "abc", "count": 1}})
    entry = {"priceBookId": book_id, "fileSha": "abc", "vendor": "hager", "file": "hager_price_book_18.pdf",
             "effective": "2026-03-02"}
    db[names.PRICE_BOOK_ENTRIES].insert_many([
        {**entry, "model": "BB1279", "size": '4-1/2" x 4-1/2"', "finish": "US26D", "listPrice": 23.76,
         "section": "Commercial Hinges", "page": 68, "printedPage": "62"},
        {**entry, "model": "5100", "finish": "ALM", "listPrice": 440.71, "description": "Regular arm",
         "section": "Door Controls - 5100 Series", "page": 136, "printedPage": "5"},
        {**entry, "model": "5100", "finish": "ALM", "listPrice": 512.00, "description": "Hold open arm",
         "section": "Door Controls - 5100 Series", "page": 136, "printedPage": "5"},
    ])
    legend = scratch / SLUG / "extracted" / "hardware_sets.json"
    legend.parent.mkdir(parents=True)
    legend.write_text(json.dumps(SETS), encoding="utf-8")

    lib = MatchAndPrice.reference_library
    monkeypatch.setattr(lib, "load_special_nets", lambda: {"effective_date": "2026-03-02", "items": [
        {"item_code": "051456", "part_number": "431S", "net_price": 43.33,
         "description": '431S Commercial Saddle Threshold 48" Mill Finish'}]})
    monkeypatch.setattr(lib, "load_vendor_tiers", lambda: {"vendors": [
        {"key": "hager", "categories": {"architectural_hinges": 0.21, "door_controls": 0.30},
         "effective_date": "2026-03-02"}]})
    monkeypatch.setattr(lib, "resolve_finish", lambda text: {"us_code": "US26D"} if text in ("626", "US26D") else None)
    monkeypatch.setattr(lib, "sheet_lapsed", lambda effective: False)
    monkeypatch.setattr(MatchAndPrice.pricing, "special_margin", lambda gc, brand: None)
    monkeypatch.setattr(MatchAndPrice.ops_jobs, "holds_lease", lambda job: _true())
    asked: list[str] = []

    async def model(question, prompt, images=()):
        # Never a real model in a test. This one picks the hold-open arm, row 2.
        asked.append(prompt)
        return ai.Asked(CatalogChoice(choice=2, reason="the legend says hold open"))

    monkeypatch.setattr(MatchAndPrice.ops_ai, "ask", model)
    try:
        yield project, db, asked
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db, settings.storage_root = previous_db, previous_root
        shutil.rmtree(scratch, ignore_errors=True)
        db_module._client = None


async def _true() -> bool:
    return True


def _lines(db, project) -> dict[str, dict]:
    return {line["lineKey"]: line for line in db[names.ESTIMATE_LINES].find({"projectId": project["_id"]})}


def test_a_take_off_is_priced_in_code_and_rolled_up_without_its_alternates(bid) -> None:
    from cbc.modules.quoting.features import MatchAndPrice

    project, db, asked = bid
    note = run(MatchAndPrice.price_in_code({"_id": ObjectId(), "type": "match_and_price"}, project))
    assert "priced in code: 4/11 lines have a cost" in note, note
    lines = _lines(db, project)

    # Each in-scope door's door and frame, one line per specification: CBC quotes
    # them (requirements 1.1), priced from the door supplier - never off a list.
    doors = {key: line for key, line in lines.items() if key.startswith(("door:", "frame:"))}
    assert len(doors) == 4 and all(line["cost"] is None for line in doors.values())
    rated_door = next(line for key, line in doors.items() if key.startswith("door:") and "90 MIN" in key)
    assert rated_door["openings"] == ["101"] and "fire_rated" in rated_door["flags"]
    assert "price from the door supplier" in rated_door["costSourceDetail"]

    hinges = lines["1:01"]  # 1 1/2 pair = 3 a door, on the two in-scope doors that cite the set
    assert (hinges["qty"], hinges["qtyPerOpening"], hinges["openings"]) == (6.0, 3.0, ["101", "102"])
    assert (hinges["cost"], hinges["costSource"], hinges["multiplierTier"]) == (4.99, "LIST_X_MULTIPLIER", "architectural_hinges")
    assert hinges["division"] == "08 71 00" and hinges["sell"] is not None  # rolled up by persist
    assert hinges["stock"] is True and "non_stock" not in hinges["flags"]  # BB1279 is on Hager's stock list
    assert (lines["1:02"]["cost"], lines["1:02"]["costSource"]) == (43.33, "SPECIAL_NET")
    assert lines["1:03"]["manufacturer"] == "Hager" and lines["1:03"]["cost"] is None
    assert lines["1:03:allegion"]["alternateGroup"] == "Allegion as specified"
    assert (lines["1:04"]["alternateGroup"], lines["1:04"]["cost"]) == ("Supplied by others", 3.82)
    assert "needs a distributor or vendor quote" in lines["1:05"]["costSourceDetail"]
    # One model at two prices: the model was asked once, chose row 2, and the line says so.
    closer = lines["1:06"]
    assert len(asked) == 1 and "1. 5100 ALM $440.71" in asked[0] and "2. 5100 ALM $512.0" in asked[0]
    assert (closer["cost"], closer["costSource"]) == (153.6, "LIST_X_MULTIPLIER")
    assert "model_chose_match" in closer["flags"] and "the legend says hold open" in closer["costSourceDetail"]

    quote = db[names.QUOTES].find_one({"projectId": project["_id"]})
    base = [line for line in lines.values() if not line.get("alternateGroup")]
    assert quote["subtotal"] == round(sum(line.get("extended") or 0 for line in base), 2)
    assert quote["subtotal"] < round(sum(line.get("extended") or 0 for line in lines.values()), 2)

    # The gate sees each door's parts now that a line names its doors: the
    # unrated door gets its candidates; the 90-minute one is held, because no
    # catalog row says it carries a rating (Matrix 7.3).
    unrated = db[names.OPENINGS].find_one({"projectId": project["_id"], "mark": "102"})
    assert {c["part"] for c in unrated["matchCandidates"]} == {"BB1279", "346C"}
    rated = db[names.OPENINGS].find_one({"projectId": project["_id"], "mark": "101"})
    assert rated["ratingConflict"] is True and rated["matchCandidates"] == []


def test_a_re_price_keeps_what_an_estimator_typed_and_refreshes_the_rest(bid) -> None:
    from cbc.modules.quoting.features import MatchAndPrice

    project, db, _asked = bid
    job = {"_id": ObjectId(), "type": "match_and_price"}
    run(MatchAndPrice.price_in_code(job, project))
    db[names.ESTIMATE_LINES].update_one(
        {"projectId": project["_id"], "lineKey": "1:05"},
        {"$set": {"cost": 88.0, "costSource": "VENDOR_RFQ", "costSourceDetail": "Vendor RFQ R-1"},
         "$push": {"overrides": {"after": {"cost": 88.0, "costSource": "VENDOR_RFQ", "costSourceDetail": "Vendor RFQ R-1"}}}},
    )
    note = run(MatchAndPrice.price_in_code(job, project))
    assert "1 kept as the estimator left them" in note, note
    edited = _lines(db, project)["1:05"]
    assert (edited["cost"], edited["costSource"]) == (88.0, "VENDOR_RFQ")
    assert edited["qty"] == 2.0 and edited["openings"] == ["101", "102"]


def test_a_door_moved_into_an_alternate_is_priced_as_its_own_lines(bid) -> None:
    """FR-14: the estimator puts door 102 in Alternate 1 on the take-off; the set's
    hardware splits - the base keeps door 101's, the alternate prices door 102's -
    and the Allegion part as specified is a substitution for its Hager equal."""
    from cbc.modules.quoting.features import MatchAndPrice

    project, db, _asked = bid
    db[names.OPENINGS].update_one({"projectId": project["_id"], "mark": "102"},
                                  {"$set": {"alternateGroup": "Alternate 1"}})
    run(MatchAndPrice.price_in_code({"_id": ObjectId(), "type": "match_and_price"}, project))
    lines = _lines(db, project)

    base, alternate = lines["1:01"], lines["1:01@Alternate 1"]
    assert (base["openings"], base["qty"], base.get("alternateGroup")) == (["101"], 3.0, None)
    assert (alternate["openings"], alternate["qty"], alternate["alternateGroup"]) == (["102"], 3.0, "Alternate 1")
    assert lines["1:03"]["deductedBy"] == ["Allegion as specified"]
    quote = db[names.QUOTES].find_one({"projectId": project["_id"]})
    assert quote["subtotal"] == round(sum(l.get("extended") or 0 for l in lines.values() if not l.get("alternateGroup")), 2)


def test_a_part_off_its_makers_stock_list_says_so() -> None:
    """NR-6: off the list is usually a lead time. A maker with no list says nothing."""
    from cbc.modules.quoting.features import MatchAndPrice

    lists = {"hager": {"BB1279", "5100"}}
    rows = [{"manufacturer": "Hager", "part_number": "BB1279-4.5X4.5", "division": "08 71 00", "flags": []},
            {"manufacturer": "Hager", "part_number": "2700", "division": "08 71 00", "flags": []},
            {"manufacturer": "Rockwood", "part_number": "K1050", "division": "08 71 00", "flags": []},
            {"manufacturer": "Hager", "part_number": "B-212", "division": "10 28 13", "flags": []}]
    for row in rows:
        MatchAndPrice._mark_stock(row, lists)
    assert [(row.get("stock"), row["flags"]) for row in rows] == [
        (True, []), (False, ["non_stock"]), (None, []), (None, [])]


def test_what_the_bid_request_gives_to_others_stays_out_of_the_bid(bid) -> None:
    """FR-1: "hardware only" in the request's scope notes - the doors and frames
    stay on the quote as supplied by others, and out of the total."""
    from cbc.modules.quoting.features import MatchAndPrice

    project, db, _asked = bid
    run(MatchAndPrice.price_in_code({"_id": ObjectId(), "type": "match_and_price"},
                                    {**project, "rfpText": "Hardware only per the GC's email"}))
    lines = _lines(db, project)
    doors = [line for key, line in lines.items() if key.startswith(("door:", "frame:"))]
    assert doors and all(line["alternateGroup"] == "Supplied by others" for line in doors)
    assert all("Hardware only" in line["notes"] and "excluded_by_request" in line["flags"] for line in doors)
    assert lines["1:01"].get("alternateGroup") is None, "the hardware is still the bid"
