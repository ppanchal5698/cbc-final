"""extract_bid_set in code (v2): a bid set read by the parsers and landed in
`openings` - against a throwaway Mongo, no model and no Claude pass."""
from __future__ import annotations

import asyncio
import json
import os
import shutil

import pytest
from bson import ObjectId

from cbc.shared.config import settings
from cbc.shared.persistence import names
from tests.shared import FIXTURES, mongo_client

TEST_DB = "cbc_test_extract_in_code"
SLUG = "extract_in_code_fixture"

ROWS = [
    ["DOOR NO.", "WIDTH", "HEIGHT", "FIRE RATING", "HARDWARE GROUP"],
    ["101", "3'-0\"", "7'-0\"", "90 MIN", "GROUP 1"],
    ["102", "3'-0\"", "7'-0\"", "20 MIN", "GROUP 1"],
    ["A12", "3'-6\"", "7'-0\"", "NONE", "GROUP 2"],
]


def run(coro):
    from cbc.shared import mongo as db_module

    db_module._client = None
    try:
        return asyncio.run(coro)
    finally:
        db_module._client = None


def _schedule_sheet(path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_text((72, 60), "DOOR SCHEDULE", fontsize=14)
    for row, cells in enumerate(ROWS):
        for column, text in enumerate(cells):
            page.insert_text((72 + column * 150, 120 + row * 24), text, fontsize=9)
    doc.save(path)
    doc.close()


async def _true(*_args, **_kwargs) -> bool:
    return True


@pytest.fixture()
def bid(monkeypatch):
    from cbc.modules.extraction.features import ExtractBidSet
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
    monkeypatch.setenv("STORAGE_ROOT", str(scratch))  # the sheet map's lookup (cbc.shared.paths)
    raw.drop_database(TEST_DB)
    db_module._client = None

    uploads = scratch / SLUG / "uploads" / "raw"
    uploads.mkdir(parents=True)
    _schedule_sheet(uploads / "A601.pdf")
    project = {"_id": ObjectId(), "slug": SLUG, "code": "EX-001", "name": "Extract fixture"}
    raw[TEST_DB][names.BID_REQUESTS].insert_one(dict(project))
    monkeypatch.setattr(ExtractBidSet.ops_jobs, "holds_lease", _true)
    # Intake binds the documents port when the worker registers its jobs.
    monkeypatch.setattr(ExtractBidSet.documents, "mark_received", _true)
    try:
        yield project, raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db, settings.storage_root = previous_db, previous_root
        shutil.rmtree(scratch, ignore_errors=True)
        db_module._client = None


def _job(project: dict, kind: str = "extract_bid_set") -> dict:
    return {"_id": ObjectId(), "type": kind, "projectId": project["_id"], "payload": {}}


def test_a_bid_set_is_read_in_code_and_lands_without_a_pass(bid) -> None:
    from cbc.modules.extraction.api import passes
    from cbc.modules.extraction.features import ExtractBidSet

    project, db = bid
    job = _job(project)

    assert run(passes.prepare(job, project, job["payload"])) is True
    note = run(ExtractBidSet.extract_in_code(job, project))

    doors = {d["mark"]: d for d in db[names.OPENINGS].find({"projectId": project["_id"]})}
    assert sorted(doors) == ["101", "102", "A12"], note
    assert doors["101"]["hwSet"] and doors["101"]["fireRating"]
    # Every row says where it was read: the page, and the row on it.
    for door in doors.values():
        assert door["evidence"]["sourcePage"] == 1 and door["evidence"]["bbox"], door["evidence"]
    stored = db[names.BID_REQUESTS].find_one({"_id": project["_id"]})
    assert stored["stage"] == "extraction"


def test_the_extract_job_runs_in_code_when_the_switch_says_so(monkeypatch) -> None:
    """v2 runs the take-off as the job's own work - no wave, no Claude pass."""
    from cbc.modules.extraction.features import ExtractBidSet

    seen: dict = {}

    async def run_pass(job, **kwargs):
        seen.update(kwargs)

    async def engine() -> str:
        return "v2"

    monkeypatch.setattr(ExtractBidSet.ops_pipeline, "extraction_engine", engine)
    monkeypatch.setattr(ExtractBidSet.pipeline, "run_pass", run_pass)
    asyncio.run(ExtractBidSet.run({"_id": ObjectId(), "type": "extract_bid_set"}))

    assert seen["work"] is ExtractBidSet.extract_in_code
    assert "wave_for" not in seen


# ── what the model is asked: only what the parsers could not read ────────────


def _seeded(tmp_path, monkeypatch, rows):
    from cbc.modules.extraction.features import ReadByModel

    root = tmp_path / "projects"
    path = root / SLUG / "extracted" / "line_items.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"openings": rows}), encoding="utf-8")
    monkeypatch.setattr(ReadByModel.storage, "project_dir", lambda slug: root / slug)
    monkeypatch.setenv("STORAGE_ROOT", str(root))  # the sheet map's lookup
    monkeypatch.setattr(ReadByModel.pretakeoff, "_resolve", lambda slug, p: tmp_path / "plan.pdf")
    monkeypatch.setattr(ReadByModel.pdfpages, "page_image",
                        lambda pdf, page, dpi, out, region=None: {"image_path": str(tmp_path / "crop.png")})
    return path


def test_a_handing_the_schedule_did_not_give_is_read_off_the_plan_and_flagged(tmp_path, monkeypatch) -> None:
    from cbc.modules.extraction.domain.questions import DoorHanding, Handings
    from cbc.modules.extraction.features import ReadByModel
    from cbc.shared import ai

    path = _seeded(tmp_path, monkeypatch, [
        {"door_number": "101"}, {"door_number": "102", "handing": "LHR"}, {"door_number": "103"},
    ])
    monkeypatch.setattr(ReadByModel.visual_pages, "handing_regions", lambda slug: [
        {"path": "plan.pdf", "page": 3, "region": [0, 0, 300, 300], "marks": ["101", "102", "103"]},
        {"path": "plan.pdf", "page": 4, "region": [0, 0, 300, 300], "marks": ["104"]},
    ])
    asked: list[str] = []

    async def model(question, prompt, images=()):
        asked.append(prompt)
        if len(asked) > 1:
            return ai.Asked(None, error="provider down")
        return ai.Asked(Handings(doors=[
            DoorHanding(mark="101", handing="RH", reason="hinges right, swings into the office"),
            DoorHanding(mark="102", handing="LH", reason="the schedule already says"),
            DoorHanding(mark="103", handing="UNCLEAR", reason="a pair"),
            DoorHanding(mark="999", handing="LH", reason="not a door on this bid"),
        ]))

    monkeypatch.setattr(ReadByModel.ops_ai, "ask", model)

    assert asyncio.run(ReadByModel.handing(SLUG)) == 1

    rows = {r["door_number"]: r for r in json.loads(path.read_text(encoding="utf-8"))["openings"]}
    assert rows["101"]["handing"] == "RH" and "handing_read_from_plan" in rows["101"]["flags"]
    assert rows["102"]["handing"] == "LHR", "a handing the schedule printed is never the model's to change"
    assert "handing" not in rows["103"] or rows["103"]["handing"] is None
    assert asked == ["Door marks: 101, 102, 103", "Door marks: 104"]


def test_no_provider_leaves_every_row_as_it_was(tmp_path, monkeypatch) -> None:
    from cbc.modules.extraction.features import ReadByModel

    path = _seeded(tmp_path, monkeypatch, [{"door_number": "101"}])
    monkeypatch.setattr(ReadByModel.visual_pages, "handing_regions", lambda slug: [
        {"path": "plan.pdf", "page": 3, "region": [0, 0, 300, 300], "marks": ["101"]},
    ])

    async def no_provider(question, prompt, images=()):
        raise RuntimeError("no provider configured")

    monkeypatch.setattr(ReadByModel.ops_ai, "ask", no_provider)

    assert asyncio.run(ReadByModel.handing(SLUG)) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["openings"] == [{"door_number": "101"}]


def test_a_project_field_the_record_lacks_is_read_off_the_title_block_with_its_words(tmp_path, monkeypatch) -> None:
    from cbc.modules.extraction.domain.questions import Printed, TitleBlock
    from cbc.modules.extraction.features import ReadByModel
    from cbc.shared import ai

    path = _seeded(tmp_path, monkeypatch, [])
    extracted = path.parent
    (extracted / "_sheetmap.json").write_text(json.dumps({"files": [{"path": "uploads/raw/A101.pdf"}]}), encoding="utf-8")
    (extracted / "scope_metadata.json").write_text(json.dumps({
        "project_name": None, "architect": "Franz Architects", "gc": None,
        "flags": ["title_block_not_read - project_name is null because no pass has read the drawings for it",
                  "title_block_not_read - gc is null because no pass has read the drawings for it"],
    }), encoding="utf-8")
    monkeypatch.setattr(ReadByModel.pdfpages, "page_text", lambda pdf, page: "SHELL BUILDING A  TBD HWY 77")
    seen: list[str] = []

    async def model(question, prompt, images=()):
        seen.append(prompt)
        empty = Printed(value=None)
        return ai.Asked(TitleBlock(
            project_name=Printed(value="Shell Building A", excerpt="SHELL BUILDING A"),
            brand=empty, address=empty, city=empty, state=empty, gc=empty, project_number=empty,
            architect=Printed(value="Someone Else", excerpt="a consultant's stamp"),
        ))

    monkeypatch.setattr(ReadByModel.ops_ai, "ask", model)

    assert asyncio.run(ReadByModel.title_block(SLUG)) == 1

    meta = json.loads((extracted / "scope_metadata.json").read_text(encoding="utf-8"))
    assert meta["project_name"] == "Shell Building A"
    assert meta["field_sources"]["project_name"]["excerpt"] == "SHELL BUILDING A"
    assert meta["architect"] == "Franz Architects", "a field the record carries is not asked about"
    assert meta["gc"] is None and len(meta["flags"]) == 1 and "gc" in meta["flags"][0]
    assert "architect" not in seen[0] and "SHELL BUILDING A" in seen[0]


def test_a_schedule_with_no_text_layer_is_read_off_pictures_of_the_sheet(tmp_path, monkeypatch) -> None:
    """Waxahachie's door schedule and hardware legend are outlined letters: no text
    for any parser, OCR included. Where the tables are, then what each says."""
    from cbc.modules.extraction.domain.questions import (
        HardwareSet, ScheduleRow, ScheduleRows, SetItem, TableOnSheet, TablesOnSheet,
    )
    from cbc.modules.extraction.features import ReadByModel
    from cbc.shared import ai

    path = _seeded(tmp_path, monkeypatch, [])
    extracted = path.parent
    (extracted / "_sheetmap.json").write_text(json.dumps({"files": [{"path": "uploads/raw/wax.pdf", "pages": [
        {"source_page": 4, "roles": ["door_schedule_candidate"], "needs_visual_read": True},
        {"source_page": 16, "roles": ["door_schedule_candidate"], "needs_visual_read": True},
        {"source_page": 20, "roles": ["floor_plan"], "needs_visual_read": True},  # not a schedule's sheet
        {"source_page": 21, "roles": ["door_schedule"], "needs_visual_read": False},  # the parser's to read
    ]}]}), encoding="utf-8")
    monkeypatch.setattr(ReadByModel.pdfpages, "page_size", lambda pdf, page: {"width": 2592.0, "height": 1728.0})
    asked: list[tuple[str, str]] = []

    async def model(question, prompt, images=()):
        asked.append((question.name, prompt))
        if question.name == "find_schedule_tables":
            if len(asked) == 1:  # sheet 4: elevations, no tables
                return ai.Asked(TablesOnSheet(tables=[]))
            return ai.Asked(TablesOnSheet(tables=[
                TableOnSheet(kind="door_schedule", box=[0.3, 0.05, 0.5, 0.2], title="DOOR SCHEDULE"),
                TableOnSheet(kind="hardware_set", box=[0.5, 0.08, 0.7, 0.18], title="H-1"),
            ]))
        if question.name == "read_door_schedule":
            return ai.Asked(ScheduleRows(rows=[
                ScheduleRow(door_number="1", width="6'-0\"", height="7'-0\"", door_material="ALUM", hardware_set="H-1"),
                ScheduleRow(door_number="3", width="3'-0\"", height="7'-0\"", door_material="HM", hardware_set="H-4"),
            ]))
        return ai.Asked(HardwareSet(set_id="H-1", name="FRONT ENTRY/EXIT SF DOUBLE DOORS", items=[
            SetItem(qty="(1)", description="INTERCHANGEABLE CORE", manufacturer="FALCON", part="C647A", supplied_by="GC"),
        ]))

    monkeypatch.setattr(ReadByModel.ops_ai, "ask", model)

    assert asyncio.run(ReadByModel.schedules(SLUG)) == {"doors": 2, "sets": 1}

    assert [name for name, _ in asked] == [
        "find_schedule_tables", "find_schedule_tables", "read_door_schedule", "read_hardware_set",
    ]
    doors = json.loads(path.read_text(encoding="utf-8"))["openings"]
    assert [(d["door_number"], d["hardware_set"], d["source_page"]) for d in doors] == [("1", "H-1", 16), ("3", "H-4", 16)]
    # The table's box on the page, padded: where the estimator looks for the row.
    assert doors[0]["bbox"] == [738.72, 60.48, 1334.88, 371.52]
    assert "read_by_model" in doors[0]["flags"] and doors[0]["page_size"] == {"width": 2592.0, "height": 1728.0}
    # Scope is decided in code for a row the model read too: an aluminium storefront
    # door is not CBC's to quote.
    assert doors[0]["in_scope"] is False and doors[1]["in_scope"] is not False
    sets = json.loads((extracted / "hardware_sets.json").read_text(encoding="utf-8"))["sets"]
    assert sets[0]["set_id"] == "H-1" and sets[0]["items"][0]["part"] == "C647A"


def test_a_take_off_the_parsers_read_asks_nothing(tmp_path, monkeypatch) -> None:
    from cbc.modules.extraction.features import ReadByModel

    _seeded(tmp_path, monkeypatch, [{"door_number": "101"}])
    (tmp_path / "projects" / SLUG / "extracted" / "hardware_sets.json").write_text(
        json.dumps({"sets": [{"set_id": "1", "items": []}]}), encoding="utf-8")

    async def model(question, prompt, images=()):
        raise AssertionError("nothing to ask")

    monkeypatch.setattr(ReadByModel.ops_ai, "ask", model)
    assert asyncio.run(ReadByModel.schedules(SLUG)) == {}
