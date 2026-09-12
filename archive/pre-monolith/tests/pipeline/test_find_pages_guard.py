"""T-08: MCP find_pages must not load every catalog without a vendor filter."""
from __future__ import annotations

from _runtime import load_server


def _catalog_row(
    vendor: str = "hager",
    title: str = "3400 Series Locks",
    built_at: str = "2026-01-01T00:00:00+00:00",
) -> dict:
    return {
        "_id": f"{vendor}_book",
        "catalogId": f"{vendor}_book",
        "vendor": vendor,
        "fileName": f"{vendor}.pdf",
        "fileHash": "sha256:x",
        "builtAt": built_at,
        "pages": [
            {
                "pdfPage": 1,
                "title": title,
                "description": "storeroom lock",
                "codePrefixes": ["3400"],
                "keywords": ["lock"],
                "hasPrices": True,
                "kind": "price_table",
                "confidence": 1.0,
            }
        ],
    }


def _header(vendor: str = "hager", built_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {"_id": f"{vendor}_book", "vendor": vendor, "builtAt": built_at}


def test_unfiltered_find_pages_guards_above_ten_catalogs(monkeypatch) -> None:
    catalog = load_server("catalog")
    headers = [{"_id": f"c{i}", "vendor": f"v{i}"} for i in range(11)]
    monkeypatch.setattr(catalog.reader, "list_catalogs", lambda vendor=None: headers)

    def boom(*_args, **_kwargs):
        raise AssertionError("all_catalogs must not run without a vendor filter")

    monkeypatch.setattr(catalog.reader, "all_catalogs", boom)
    result = catalog.find_pages("3400 lock")
    assert result["count"] == 0
    assert result["pages"] == []
    assert "Pass vendor=" in result["note"]


def test_vendor_filtered_find_pages_still_ranks(monkeypatch) -> None:
    catalog = load_server("catalog")
    catalog.clear_find_pages_cache()
    monkeypatch.setattr(
        catalog.reader,
        "list_catalogs",
        lambda vendor=None: [_header()],
    )
    monkeypatch.setattr(
        catalog.reader, "all_catalogs", lambda vendor=None: [_catalog_row()]
    )
    result = catalog.find_pages("3400", vendor="hager", limit=3)
    assert result["count"] >= 1
    assert result["pages"][0]["pdf_page"] == 1


def test_second_find_pages_does_not_refetch(monkeypatch) -> None:
    catalog = load_server("catalog")
    catalog.clear_find_pages_cache()
    calls = {"n": 0}

    def counting(vendor=None):
        calls["n"] += 1
        return [_catalog_row()]

    monkeypatch.setattr(
        catalog.reader, "list_catalogs", lambda vendor=None: [_header()]
    )
    monkeypatch.setattr(catalog.reader, "all_catalogs", counting)
    first = catalog.find_pages("3400 lock", vendor="hager", limit=3)
    second = catalog.find_pages("3400 lock", vendor="hager", limit=3)
    assert calls["n"] == 1
    assert first["pages"] == second["pages"]


def test_built_at_bump_misses_find_pages_cache(monkeypatch) -> None:
    catalog = load_server("catalog")
    catalog.clear_find_pages_cache()
    calls = {"n": 0}
    stamp = {"v": "2026-01-01T00:00:00+00:00"}

    def headers(vendor=None):
        return [_header(built_at=stamp["v"])]

    def counting(vendor=None):
        calls["n"] += 1
        return [_catalog_row(built_at=stamp["v"])]

    monkeypatch.setattr(catalog.reader, "list_catalogs", headers)
    monkeypatch.setattr(catalog.reader, "all_catalogs", counting)
    catalog.find_pages("3400", vendor="hager")
    stamp["v"] = "2026-06-01T00:00:00+00:00"
    catalog.find_pages("3400", vendor="hager")
    assert calls["n"] == 2


def test_all_catalogs_projects_away_profile(monkeypatch) -> None:
    from cbc.pageindex import reader

    seen: dict = {}

    class Cursor:
        def limit(self, _n):
            return []

    class Collection:
        def find(self, query, projection=None):
            seen["query"] = query
            seen["projection"] = projection
            return Cursor()

    monkeypatch.setattr(reader, "_collection", lambda: Collection())
    reader.all_catalogs()
    assert seen["projection"]["profile"] == 0
    assert seen["projection"]["pages.rows"] == 0
    assert seen["projection"]["pages.sheet"] == 0
