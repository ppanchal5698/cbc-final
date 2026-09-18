"""Product-catalog lookup / search prefer curated catalogItems before PDF."""
from __future__ import annotations

from typing import Any

import pytest

from cbc.modules.catalog.api.pageindex import reader


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)

    def sort(self, *_a: Any, **_k: Any) -> _FakeCursor:
        self._rows.sort(key=lambda row: str(row.get("part") or ""))
        return self

    def limit(self, n: int) -> _FakeCursor:
        self._rows = self._rows[:n]
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeItems:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for row in self.rows:
            if _matches(row, query):
                return row
        return None

    def find(self, query: dict[str, Any]) -> _FakeCursor:
        return _FakeCursor([row for row in self.rows if _matches(row, query)])


def _eval_clause(row: dict[str, Any], clause: dict[str, Any]) -> bool:
    if "$and" in clause:
        return all(_eval_clause(row, c) for c in clause["$and"])
    if "$or" in clause:
        return any(_eval_clause(row, c) for c in clause["$or"])
    for key, cond in clause.items():
        val = row.get(key)
        if isinstance(cond, dict):
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$exists" in cond:
                exists = key in row and val is not None
                if bool(cond["$exists"]) != exists and not (
                    not cond["$exists"] and key not in row
                ):
                    # treat missing key as not exists
                    if cond["$exists"] is False:
                        if key in row and val not in (None, ""):
                            return False
                    else:
                        if key not in row:
                            return False
            if "$regex" in cond:
                import re

                flags = re.I if "i" in str(cond.get("$options", "")) else 0
                if val is None or not re.search(cond["$regex"], str(val), flags):
                    return False
            if "$in" in cond and val not in cond["$in"]:
                return False
        elif val != cond:
            return False
    return True


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    return _eval_clause(row, query)


@pytest.fixture
def catalog_rows(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows = [
        {
            "part": "010108",
            "model": "3510",
            "description": "Grade 2 Passage",
            "manufacturer": "Hager",
            "vendorKey": "hager",
            "cost": 53.68,
            "listPrice": None,
            "multiplier": None,
            "defaultMargin": 0.27,
            "seedSource": "catalog.md + catalogs/ 2026 baseline",
        },
        {
            "part": "3510-LONG",
            "model": "3510 2-3/4 US26D",
            "description": "Passage lock long",
            "manufacturer": "Hager",
            "vendorKey": "hager",
            "cost": 60.0,
            "seedSource": "catalog.md + catalogs/ 2026 baseline",
        },
        {
            "part": "BAD-OCR",
            "model": "OCR",
            "description": "ingest junk",
            "manufacturer": "Hager",
            "vendorKey": "hager",
            "cost": 1.0,
            "seedSource": "price book ingest",
        },
        {
            "part": "HAND-1",
            "model": "HAND",
            "description": "Hand added grab bar",
            "manufacturer": "Bobrick",
            "vendorKey": "bobrick",
            "cost": 100.0,
            # no seedSource — estimator-added
        },
    ]
    monkeypatch.setattr(reader, "_items_collection", lambda: _FakeItems(rows))
    return rows


def test_lookup_exact_part(catalog_rows: list[dict[str, Any]]) -> None:
    hit = reader.lookup_catalog_item("010108")
    assert hit is not None
    assert hit["cost"] == 53.68


def test_lookup_prefix_model(catalog_rows: list[dict[str, Any]]) -> None:
    hit = reader.lookup_catalog_item("3510")
    assert hit is not None
    assert hit["part"] in {"010108", "3510-LONG"}


def test_lookup_skips_ingest(catalog_rows: list[dict[str, Any]]) -> None:
    assert reader.lookup_catalog_item("BAD-OCR") is None


def test_lookup_allows_hand_added(catalog_rows: list[dict[str, Any]]) -> None:
    hit = reader.lookup_catalog_item("HAND-1")
    assert hit is not None
    assert hit["cost"] == 100.0


def test_search_ranks_exact_first(catalog_rows: list[dict[str, Any]]) -> None:
    items = reader.search_catalog_items("3510", limit=5)
    assert items
    assert items[0]["part"] in {"010108", "3510-LONG"}
    assert all(i["part"] != "BAD-OCR" for i in items)
