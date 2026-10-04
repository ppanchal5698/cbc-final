"""Every reader of hardware_sets.json sees the sets, whichever key wrote them.

The legend seed writes `sets`, the product-matcher `groups`, the normaliser
expected `hardware_sets`; each reader had its own list and none had all three.
Pre-pricing read no sets from a matcher's file, so a re-price after matching
rebuilt priced/line_items.json with zero lines over the agent's patched work.
"""
from __future__ import annotations

import json

import pytest

import cbc.shared.storage as storage_mod
from cbc.modules.catalog.api import matchcache
from cbc.modules.extraction.api.normalize_artifacts import normalize_hardware_sets_payload
from cbc.modules.pricing.api import catalog_baseline_backfill, list_x_backfill, preprice
from cbc.shared.hardware_sets import SET_KEYS

ITEM = {"part_number": "BB1191", "manufacturer": "Hager", "quantity": 1}


@pytest.mark.parametrize("key", SET_KEYS)
def test_every_reader_sees_the_items_under_any_key(key: str) -> None:
    payload = {key: [{"hardware_set": "GROUP 1", "items": [dict(ITEM)]}]}

    assert len(preprice._sets(payload)) == 1
    assert len(matchcache._iter_items(payload)) == 1
    for backfill in (catalog_baseline_backfill, list_x_backfill):
        found: list = []
        backfill._collect_items(payload, found)
        assert len(found) == 1, backfill.__name__


def test_manufacturer_aliases_reach_a_matchers_groups() -> None:
    payload = {"groups": [{"items": [{"specified": {"manufacturer": "VONDUPLIN"}}]}]}
    item = normalize_hardware_sets_payload(payload)["groups"][0]["items"][0]
    assert item["specified"]["manufacturer"] == "Von Duprin"


def _bid(tmp_path, monkeypatch, hardware: dict) -> object:
    root = tmp_path / "projects" / "demo_bid"
    (root / "extracted").mkdir(parents=True)
    (root / "priced").mkdir(parents=True)
    (root / "extracted" / "hardware_sets.json").write_text(json.dumps(hardware), encoding="utf-8")
    # The priced file as a pass leaves it: still this seed's stamp, one patched line.
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"source": preprice.SOURCE, "lines": [{"line_id": "GROUP 1-00", "cost": 41.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)
    monkeypatch.delenv("P21_BASE_URL", raising=False)
    return root


def test_a_re_price_after_matching_reads_the_matchers_groups(tmp_path, monkeypatch) -> None:
    root = _bid(tmp_path, monkeypatch, {"groups": [{"hardware_set": "GROUP 1", "items": [dict(ITEM)]}]})

    preprice.seed_line_items("demo_bid")
    lines = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))["lines"]
    assert len(lines) == 1


def test_a_seed_that_reads_no_sets_keeps_the_priced_lines(tmp_path, monkeypatch) -> None:
    root = _bid(tmp_path, monkeypatch, {"some_future_key": [{"items": [dict(ITEM)]}]})

    result = preprice.seed_line_items("demo_bid")
    assert result["written"] is False
    lines = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))["lines"]
    assert lines == [{"line_id": "GROUP 1-00", "cost": 41.0}]
