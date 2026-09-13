"""Atomic JSON writes and mid-chain scope validation hooks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tests.shared import ROOT


def test_atomic_write_json_round_trip(tmp_path) -> None:
    from cbc.shared.storage import atomic_write_json

    target = tmp_path / "extracted" / "scope_metadata.json"
    atomic_write_json(target, {"brand": "Dutch Bros", "state": "LA"})
    assert json.loads(target.read_text(encoding="utf-8"))["brand"] == "Dutch Bros"
    leftovers = list(target.parent.glob(".scope_metadata.json.*.tmp"))
    assert leftovers == []


def test_post_extraction_blocks_invalid_scope_summary(tmp_path, monkeypatch) -> None:
    root = ROOT
    # `.claude/hooks`, not `agent-runtime/hooks`: settings.json registers the
    # former, so the latter was a copy that never ran and this test was the only
    # thing exercising it.
    hooks = root / ".claude" / "hooks"
    sys.path.insert(0, str(hooks))
    import post_extraction_validate as pev

    monkeypatch.setattr(pev, "ROOT", tmp_path)
    project = "demo"
    path = tmp_path / "projects" / project / "extracted" / "scope_summary.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    code = pev.check(
        {
            "tool_name": "mcp__artifact-storage__save_artifact",
            "tool_input": {"project": project, "path": "extracted/scope_summary.json"},
        }
    )
    assert code == pev.BLOCK

    path.write_text(json.dumps({"divisions": []}), encoding="utf-8")
    code = pev.check(
        {
            "tool_name": "mcp__artifact-storage__save_artifact",
            "tool_input": {"project": project, "path": "extracted/scope_summary.json"},
        }
    )
    assert code == pev.BLOCK

    path.write_text(json.dumps({"frp_in_scope": False, "divisions": []}), encoding="utf-8")
    code = pev.check(
        {
            "tool_name": "mcp__artifact-storage__save_artifact",
            "tool_input": {"project": project, "path": "extracted/scope_summary.json"},
        }
    )
    assert code == 0


def test_artifact_schema_rejects_bad_scope_summary() -> None:
    from cbc.modules.extraction.api.artifact_schema import validate_artifact_path

    assert validate_artifact_path("extracted/scope_summary.json", {"divisions": []})
    assert not validate_artifact_path(
        "extracted/scope_summary.json", {"frp_in_scope": False}
    )
    assert validate_artifact_path("extracted/scope_metadata.json", {})
    assert not validate_artifact_path(
        "extracted/scope_metadata.json", {"brand": "X", "state": "OH"}
    )
    assert not validate_artifact_path(
        "extracted/door_schedule.json", {"openings": [], "no_scope_reason": "none"}
    )
    assert validate_artifact_path(
        "extracted/door_schedule.json",
        {"openings": [{"door_number": "101", "hallucinated_price": "12.00"}]},
    )


def test_check_extraction_fails_when_frp_flag_without_file(tmp_path, monkeypatch) -> None:
    from cbc.modules.extraction.api.validation import artifacts

    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    slug = "frp_gate"
    extracted = tmp_path / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "scope_metadata.json").write_text("{}", encoding="utf-8")
    (extracted / "scope_summary.json").write_text(
        json.dumps({"frp_in_scope": True}), encoding="utf-8"
    )
    (extracted / "door_schedule.json").write_text(
        json.dumps({"openings": [], "no_scope_reason": "none"}), encoding="utf-8"
    )

    problems, warnings = artifacts.check_extraction(slug, require_scope=True)
    assert any("frp_takeoff.json" in p for p in problems)
    assert not any("frp_takeoff.json" in w for w in warnings)


def test_total_page_count(tmp_path, monkeypatch) -> None:
    import fitz

    from cbc.modules.extraction.infrastructure import sheetmap

    monkeypatch.setattr(sheetmap, "PROJECTS", tmp_path / "projects")
    slug = "pages"
    raw = tmp_path / "projects" / slug / "uploads" / "raw"
    raw.mkdir(parents=True)
    doc = fitz.open()
    try:
        for _ in range(3):
            doc.new_page()
        doc.save(raw / "a.pdf")
    finally:
        doc.close()
    assert sheetmap.total_page_count(slug) == 3


def test_exceeds_page_cap_is_cumulative_including_straggler_sets(tmp_path, monkeypatch) -> None:
    """Straggler merge re-sums all uploads/raw — not just the late delta."""
    import fitz

    from cbc.modules.extraction.infrastructure import sheetmap

    monkeypatch.setattr(sheetmap, "PROJECTS", tmp_path / "projects")
    slug = "cap_merge"
    raw = tmp_path / "projects" / slug / "uploads" / "raw"
    raw.mkdir(parents=True)

    def _pdf(name: str, n: int) -> None:
        doc = fitz.open()
        try:
            for _ in range(n):
                doc.new_page()
            doc.save(raw / name)
        finally:
            doc.close()

    _pdf("first.pdf", 3)
    over, pages = sheetmap.exceeds_page_cap(slug, max_pages=5)
    assert over is False and pages == 3

    _pdf("late_straggler.pdf", 4)  # cumulative 7
    over, pages = sheetmap.exceeds_page_cap(slug, max_pages=5)
    assert over is True and pages == 7
    # Same helper the worker uses for stragglerMerge jobs — no exemption.
    assert sheetmap.exceeds_page_cap(slug, 5)[0] is True
