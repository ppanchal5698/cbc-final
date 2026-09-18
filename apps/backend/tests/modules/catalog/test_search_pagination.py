"""Catalog product search returns accurate totals and offset pages."""
from __future__ import annotations

from typing import Any

import pytest
from bson import ObjectId

from cbc.modules.catalog.api import search as catalog_search


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)

    def sort(self, *_a: Any, **_k: Any) -> _FakeCursor:
        self._rows.sort(key=lambda row: row.get("part") or "")
        return self

    def skip(self, n: int) -> _FakeCursor:
        self._rows = self._rows[n:]
        return self

    def limit(self, n: int) -> _FakeCursor:
        self._rows = self._rows[:n]
        return self

    async def to_list(self, n: int) -> list[dict[str, Any]]:
        return list(self._rows)[:n]


class _FakeProducts:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def find(self, _query: dict[str, Any]) -> _FakeCursor:
        return _FakeCursor(self._rows)

    async def count_documents(self, _query: dict[str, Any]) -> int:
        return len(self._rows)


@pytest.mark.asyncio
async def test_search_manual_paginates_and_reports_total(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "_id": ObjectId(),
            "part": f"P{i:03d}",
            "description": f"Part {i}",
            "manufacturer": "Hager",
            "division": "08 71 00",
            "cost": float(i),
            "listPrice": None,
            "multiplier": None,
            "availability": "In stock",
            "seedSource": "catalog.md + catalogs/ 2026 baseline",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(catalog_search, "products", lambda: _FakeProducts(rows))

    page1, total = await catalog_search.search_manual(None, limit=2, offset=0)
    assert total == 5
    assert [row["part"] for row in page1] == ["P000", "P001"]

    page2, total2 = await catalog_search.search_manual(None, limit=2, offset=2)
    assert total2 == 5
    assert [row["part"] for row in page2] == ["P002", "P003"]


@pytest.mark.asyncio
async def test_search_total_is_full_count_not_page_length(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "_id": ObjectId(),
            "part": f"Z{i:02d}",
            "description": "Widget",
            "manufacturer": "Pemko",
            "division": "08 71 00",
            "cost": 1.0,
            "seedSource": "catalog.md + catalogs/ 2026 baseline",
        }
        for i in range(7)
    ]
    monkeypatch.setattr(catalog_search, "products", lambda: _FakeProducts(rows))

    async def _no_pages(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return []

    async def _indexed() -> bool:
        return True

    monkeypatch.setattr(catalog_search, "search_pages", _no_pages)
    monkeypatch.setattr(catalog_search, "index_available", _indexed)

    found = await catalog_search.search(None, limit=3, offset=3)
    assert found["total"] == 7
    assert found["counts"]["manual"] == 7
    assert [row["part"] for row in found["products"]] == ["Z03", "Z04", "Z05"]


# ── which filter the screen reaches for ─────────────────────────────────────


def test_a_part_number_query_uses_the_precise_filter() -> None:
    """`$text` tokenises `TEST-NET-1` into TEST / NET / 1.

    That matches every neighbouring part, and the page is ordered by `part`
    rather than by relevance, so the top row stopped being the one asked for: a
    search for TEST-NET-1 returned TEST-MULT-1 first and read its cost.
    """
    precise = catalog_search._manual_filter("TEST-NET-1", text=False)
    assert "$text" not in str(precise)
    part_clause = precise["$and"][-1]["$or"][0]["part"]["$regex"]
    assert part_clause.startswith("^"), part_clause
    assert "TEST" in part_clause and "NET" in part_clause


def test_a_descriptive_query_can_still_reach_the_text_index() -> None:
    """An anchored regex finds nothing for a phrase; that is what the index is for."""
    descriptive = catalog_search._manual_filter("paper towel dispenser", text=True)
    assert "$text" in str(descriptive)


def test_a_blank_query_filters_on_nothing_but_the_seed_rule() -> None:
    blank = catalog_search._manual_filter(None)
    assert "$text" not in str(blank) and "$regex" not in str(blank)
    assert blank["seedSource"] == {"$ne": "price book ingest"}


def test_division_and_manufacturer_survive_either_filter() -> None:
    for text in (False, True):
        built = str(catalog_search._manual_filter("x", division="08 71 00", manufacturer="Hager", text=text))
        assert "08 71 00" in built and "Hager" in built, text
