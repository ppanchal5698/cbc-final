"""C-08: high-confidence matches are reused; flagged ones are not."""
from __future__ import annotations

import json

from cbc.worker_kit import prompts
from cbc.modules.catalog.api import matchcache
from cbc.shared import manifests


def _isolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    monkeypatch.setattr(manifests, "ROOT", tmp_path)


def _hardware(*items) -> dict:
    return {"groups": [{"group": "GROUP 1", "items": list(items)}]}


def _item(part: str, confidence: float) -> dict:
    return {
        "specified": {"part_number": part, "finish": "630"},
        "matched": {"part_number": part, "vendor": "hager"},
        "confidence": confidence,
        "match_tier": 1 if confidence >= 0.75 else 3,
        "cost_source": "LIST_X_MULTIPLIER",
    }


def test_high_confidence_is_reused_low_is_not(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(matchcache, "catalog_watermark", lambda: "wm-1")
    slug = "demo"
    root = tmp_path / "projects" / slug
    extracted = root / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text("{}", encoding="utf-8")
    (extracted / "hardware_sets.json").write_text(
        json.dumps(_hardware(_item("3400", 0.95), _item("3500", 0.5))),
        encoding="utf-8",
    )
    written = matchcache.ingest(slug)
    keys = {row["specified"]["part_number"] for row in written["entries"]}
    assert keys == {"3400"}
    reused = matchcache.reusable(slug)
    assert [row["specified"]["part_number"] for row in reused] == ["3400"]


def test_watermark_change_clears_reuse(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    stamp = {"v": "wm-1"}
    monkeypatch.setattr(matchcache, "catalog_watermark", lambda: stamp["v"])
    slug = "demo"
    extracted = tmp_path / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text("{}", encoding="utf-8")
    (extracted / "hardware_sets.json").write_text(
        json.dumps(_hardware(_item("3400", 0.95))),
        encoding="utf-8",
    )
    matchcache.ingest(slug)
    stamp["v"] = "wm-2"
    assert matchcache.reusable(slug) == []


def test_force_and_missing_cache_are_empty(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(matchcache, "catalog_watermark", lambda: "wm")
    assert matchcache.reusable("missing") == []
    assert matchcache.reusable("missing", force=True) == []


def test_door_schedule_sha_change_clears_reuse(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(matchcache, "catalog_watermark", lambda: "wm-1")
    slug = "demo"
    extracted = tmp_path / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text("{}", encoding="utf-8")
    (extracted / "hardware_sets.json").write_text(
        json.dumps(_hardware(_item("3400", 0.95))),
        encoding="utf-8",
    )
    matchcache.ingest(slug)
    (extracted / "door_schedule.json").write_text('{"changed": true}', encoding="utf-8")
    assert matchcache.reusable(slug) == []


def test_match_prompt_includes_cached_item_unless_forced(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(matchcache, "catalog_watermark", lambda: "wm-1")
    slug = "demo"
    extracted = tmp_path / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text("{}", encoding="utf-8")
    (extracted / "hardware_sets.json").write_text(
        json.dumps(_hardware(_item("3400", 0.95))),
        encoding="utf-8",
    )
    matchcache.ingest(slug)
    project = {"slug": slug, "code": "CBC-1"}
    text = prompts.build({"type": "match_and_price", "payload": {}}, project)
    assert "Reuse these cached matches" in text
    assert "3400" in text
    forced = prompts.build(
        {"type": "match_and_price", "payload": {"force": True}}, project
    )
    assert "Reuse these cached matches" not in forced

