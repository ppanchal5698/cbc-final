"""Deterministic catalogItems cost backfill before PDF Path 2."""
from __future__ import annotations

import json

import pytest

from cbc.modules.pricing.api import catalog_baseline_backfill


def test_backfill_sets_catalog_baseline(tmp_path, monkeypatch) -> None:
    slug = "demo_bid"
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)

    (root / "extracted" / "hardware_sets.json").write_text(
        json.dumps(
            {
                "hardware_sets": [
                    {
                        "items": [
                            {
                                "matched": {
                                    "part_number": "010108",
                                    "manufacturer": "Hager",
                                }
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "priced" / "line_items.json").write_text(
        json.dumps(
            {
                "lines": [
                    {
                        "part_number": "010108",
                        "description": "Passage lock",
                        "quantity": 2,
                        "cost": None,
                        "cost_source": "MANUAL",
                        "manufacturer": "Hager",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    import cbc.shared.storage as storage_mod

    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    # The catalog lookup arrives as a bound port, not an import: pricing may not
    # import catalog without closing a cycle in the module graph.
    monkeypatch.setattr(
        catalog_baseline_backfill,
        "_lookup_catalog_item",
        lambda part, vendor=None: {
            "part": "010108",
            "cost": 53.68,
            "defaultMargin": 0.27,
            "seedSource": "catalog.md + catalogs/ 2026 baseline",
            "vendorKey": "hager",
        },
    )

    stats = catalog_baseline_backfill.backfill_priced_lines(slug)
    assert stats["filled"] == 1

    updated = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))
    line = updated["lines"][0]
    assert line["cost_source"] == "CATALOG_BASELINE"
    assert line["cost"] == 53.68
    assert line["sale_ea"] is not None
    assert line["ext_price"] is not None
    assert "catalog_baseline_backfilled" in line["flags"]


def test_backfill_skips_allegion(tmp_path, monkeypatch) -> None:
    slug = "demo_bid"
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)
    (root / "extracted" / "hardware_sets.json").write_text(
        json.dumps({"hardware_sets": []}), encoding="utf-8"
    )
    (root / "priced" / "line_items.json").write_text(
        json.dumps(
            {
                "lines": [
                    {
                        "part_number": "99EO",
                        "manufacturer": "Von Duprin",
                        "cost": None,
                        "cost_source": "DISTRIBUTOR_MANUAL",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    import cbc.shared.storage as storage_mod
    from cbc.modules.catalog.api.pageindex import reader

    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("should not look up Allegion")

    monkeypatch.setattr(reader, "lookup_catalog_item", boom)

    stats = catalog_baseline_backfill.backfill_priced_lines(slug)
    assert stats["filled"] == 0
    assert called["n"] == 0
    line = json.loads((root / "priced" / "line_items.json").read_text())["lines"][0]
    assert line["cost"] is None


def test_an_unbound_catalog_skips_the_line_rather_than_failing_the_quote(
    tmp_path, monkeypatch
) -> None:
    """The backfill is an enhancement; with no catalog bound it must do nothing quietly."""
    import cbc.shared.storage as storage_mod

    slug = "unbound_bid"
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"lines": [{"part_number": "010108", "cost": None, "cost_source": "MANUAL"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    monkeypatch.setattr(catalog_baseline_backfill, "_lookup_catalog_item", None)

    stats = catalog_baseline_backfill.backfill_priced_lines(slug)
    assert stats["filled"] == 0
    assert stats["skipped"] >= 1
