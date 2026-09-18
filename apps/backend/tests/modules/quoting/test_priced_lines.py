"""Matched artifacts survive phase boundaries without undoing estimator edits."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from cbc.modules.quoting.api import priced_lines
from cbc.modules.quoting.features import DeleteQuoteLine


@pytest.fixture()
def quote_store(tmp_path, monkeypatch):
    project = {"_id": ObjectId(), "slug": "fixture", "code": "TEST-1"}
    docs = []

    async def rows():
        for doc in docs:
            yield doc

    async def insert(operations, **_kwargs):
        docs.extend({"_id": ObjectId(), **operation._doc} for operation in operations)

    collection = SimpleNamespace(
        find=lambda _query: rows(),
        bulk_write=AsyncMock(side_effect=insert),
        find_one=AsyncMock(),
        delete_one=AsyncMock(side_effect=lambda _query: docs.clear()),
    )
    monkeypatch.setattr(priced_lines.storage, "project_dir", lambda _slug: tmp_path)
    monkeypatch.setattr(priced_lines, "estimate_lines", lambda: collection)
    monkeypatch.setattr(priced_lines, "quotes", lambda: SimpleNamespace(find_one=AsyncMock(return_value={})))
    path = tmp_path / "priced" / "line_items.json"
    path.parent.mkdir()
    return project, path, docs, collection


SHAPES = [
    pytest.param(lambda rows: {"lines": rows}, id="lines"),
    pytest.param(lambda rows: {"line_items": rows}, id="line-items-alias"),
    pytest.param(lambda rows: {"lines": [], "line_items": rows}, id="empty-canonical-alias"),
    pytest.param(lambda rows: rows, id="bare-array"),
]


def matched_lines():
    return [
        {
            "line_id": f"L{index}",
            "description": f"Matched hardware {index}",
            "part_number": f"P{index}",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "flags": ["needs source verification"],
            "notes": "Confidence: 0.64; verify the manufacturer's name on the source page",
            "opening": "Door 01",
        }
        for index in range(25)
    ]


@pytest.mark.parametrize("shape", SHAPES)
async def test_all_matched_rows_import_and_retain_evidence_on_export(quote_store, shape):
    project, path, docs, _collection = quote_store
    rows = matched_lines()
    path.write_text(json.dumps(shape(rows)), encoding="utf-8")

    counts = await priced_lines.import_quote_lines(project)
    assert counts == {"inserted": 25, "updated": 0, "skipped": 0, "removed": 0}
    assert len(docs) == 25
    await priced_lines.export_quote_lines(project)

    exported = json.loads(path.read_text(encoding="utf-8"))["lines"]
    assert len(exported) == 25
    for original, saved in zip(rows, exported):
        assert all(saved[key] == value for key, value in original.items())


@pytest.mark.parametrize("shape", SHAPES)
async def test_empty_database_never_erases_an_unimported_artifact(quote_store, shape):
    project, path, _docs, _collection = quote_store
    content = json.dumps(shape(matched_lines()), indent=2).encode()
    path.write_bytes(content)

    assert await priced_lines.export_quote_lines(project) == path
    assert path.read_bytes() == content


async def test_stored_edits_win_and_deleted_rows_are_not_merged_back(quote_store):
    project, path, docs, _collection = quote_store
    path.write_text(json.dumps({"lines": matched_lines()}), encoding="utf-8")
    await priced_lines.import_quote_lines(project)
    del docs[1:]
    docs[0].update(qty=3, cost=125, margin=0.2, sell=156.25, extended=468.75)

    await priced_lines.export_quote_lines(project)

    saved = json.loads(path.read_text(encoding="utf-8"))["lines"]
    assert len(saved) == 1
    assert (saved[0]["quantity"], saved[0]["cost"], saved[0]["ext_price"]) == (3, 125, 468.75)
    assert saved[0]["notes"] == matched_lines()[0]["notes"]


async def test_empty_import_does_not_touch_existing_mongo_rows(quote_store):
    project, path, docs, collection = quote_store
    path.write_text(json.dumps({"lines": matched_lines()}), encoding="utf-8")
    await priced_lines.import_quote_lines(project)
    assert len(docs) == 25
    collection.bulk_write.reset_mock()

    path.write_text(json.dumps({"lines": []}), encoding="utf-8")
    counts = await priced_lines.import_quote_lines(project)
    assert counts == {"inserted": 0, "updated": 0, "skipped": 25, "removed": 0}
    collection.bulk_write.assert_not_called()
    assert len(docs) == 25


async def test_deleting_last_line_clears_artifact_and_cannot_resurrect_it(quote_store, monkeypatch):
    project, path, docs, collection = quote_store
    path.write_text(json.dumps({"lines": matched_lines()[:1]}), encoding="utf-8")
    await priced_lines.import_quote_lines(project)
    collection.find_one.return_value = docs[0]
    line_id = str(docs[0]["_id"])
    monkeypatch.setattr(DeleteQuoteLine, "load", AsyncMock(return_value=project))
    monkeypatch.setattr(DeleteQuoteLine, "estimate_lines", lambda: collection)
    monkeypatch.setattr(DeleteQuoteLine.audit, "record", AsyncMock())
    monkeypatch.setattr(DeleteQuoteLine.quote_service, "persist", AsyncMock(return_value={}))

    await DeleteQuoteLine.delete_line(project["code"], line_id, "estimator")
    assert json.loads(path.read_text(encoding="utf-8"))["lines"] == []
    await priced_lines.export_quote_lines(project)
    assert json.loads(path.read_text(encoding="utf-8"))["lines"] == []
    assert docs == []


async def test_unreadable_saved_artifact_is_not_overwritten(quote_store):
    project, path, _docs, _collection = quote_store
    content = b'{"lines": [{"line_id": "L1"}'
    path.write_bytes(content)

    with pytest.raises(ValueError, match="refusing to overwrite"):
        await priced_lines.export_quote_lines(project)

    assert path.read_bytes() == content


@pytest.fixture()
def reconciling_store(tmp_path, monkeypatch):
    """A store that honours inserts, updates **and** deletes.

    The other fixture treats every bulk operation as an insert, which is exactly
    the blind spot that let the importer ship with no delete path at all.
    """
    project = {"_id": ObjectId(), "slug": "fixture", "code": "TEST-1"}
    docs: list[dict] = []

    async def rows():
        for doc in list(docs):
            yield doc

    async def apply(operations, **_kwargs):
        from pymongo import DeleteOne, InsertOne, UpdateOne

        for op in operations:
            if isinstance(op, InsertOne):
                docs.append({"_id": ObjectId(), **op._doc})
            elif isinstance(op, DeleteOne):
                target = op._filter["_id"]
                docs[:] = [d for d in docs if d["_id"] != target]
            elif isinstance(op, UpdateOne):
                target = op._filter["_id"]
                for doc in docs:
                    if doc["_id"] == target:
                        doc.update(op._doc["$set"])

    collection = SimpleNamespace(
        find=lambda _query: rows(),
        bulk_write=AsyncMock(side_effect=apply),
        find_one=AsyncMock(),
        delete_one=AsyncMock(),
    )
    monkeypatch.setattr(priced_lines.storage, "project_dir", lambda _slug: tmp_path)
    monkeypatch.setattr(priced_lines, "estimate_lines", lambda: collection)
    monkeypatch.setattr(
        priced_lines, "quotes", lambda: SimpleNamespace(find_one=AsyncMock(return_value={}))
    )
    path = tmp_path / "priced" / "line_items.json"
    path.parent.mkdir()
    return project, path, docs


def _priced(*descriptions):
    return {
        "lines": [
            {
                "line_id": f"L{n}",
                "description": text,
                "group": "Door 101",
                "group_type": "door",
                "quantity": 1,
                "cost": 10.0,
                "sale_ea": 20.0,
            }
            for n, text in enumerate(descriptions, start=1)
        ]
    }


@pytest.mark.asyncio
async def test_a_repriced_quote_drops_the_lines_pricing_no_longer_produces(
    reconciling_store,
) -> None:
    """The collection only ever grew.

    Re-pricing a bid that dropped a line left the old row in `estimateLines` and
    it went on to the quote - one re-run carried 26 rows pricing had discarded.
    """
    project, path, docs = reconciling_store

    path.write_text(json.dumps(_priced("Hinge", "Lockset", "Closer")), encoding="utf-8")
    first = await priced_lines.import_quote_lines(project)
    assert first["inserted"] == 3 and len(docs) == 3

    path.write_text(json.dumps(_priced("Hinge", "Lockset")), encoding="utf-8")
    second = await priced_lines.import_quote_lines(project)
    assert second["removed"] == 1, second
    assert sorted(d["description"] for d in docs) == ["Hinge", "Lockset"]


@pytest.mark.asyncio
async def test_a_hand_added_line_survives_a_reprice(reconciling_store) -> None:
    """There is no priced row to regenerate it from - removing it is data loss."""
    project, path, docs = reconciling_store

    path.write_text(json.dumps(_priced("Hinge")), encoding="utf-8")
    await priced_lines.import_quote_lines(project)
    docs.append({
        "_id": ObjectId(), "projectId": project["_id"], "lineKey": "hand-1",
        "description": "Site visit", "addedByHand": True,
    })

    path.write_text(json.dumps(_priced("Hinge")), encoding="utf-8")
    result = await priced_lines.import_quote_lines(project)
    assert result["removed"] == 0, result
    assert any(d.get("addedByHand") for d in docs)


@pytest.mark.asyncio
async def test_an_empty_pricing_file_removes_nothing(reconciling_store) -> None:
    """An empty agent shell must never wipe a priced quote."""
    project, path, docs = reconciling_store

    path.write_text(json.dumps(_priced("Hinge", "Lockset")), encoding="utf-8")
    await priced_lines.import_quote_lines(project)

    path.write_text(json.dumps({"lines": []}), encoding="utf-8")
    result = await priced_lines.import_quote_lines(project)
    assert result.get("removed", 0) == 0
    assert len(docs) == 2
