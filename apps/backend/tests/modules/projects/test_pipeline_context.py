"""Tests for pipeline continuity helpers."""
from __future__ import annotations

import json

from cbc.modules.projects.api import pipeline_context


def test_write_context_summarizes_artifacts(tmp_path, monkeypatch) -> None:
    from cbc.shared import paths as paths_mod
    from cbc.shared import storage as storage_mod

    slug = "demo"
    root = tmp_path / slug
    (root / "extracted").mkdir(parents=True)
    (root / "priced").mkdir(parents=True)
    (root / "extracted" / "line_items.json").write_text(
        json.dumps({"openings": [{"door_number": "01"}, {"door_number": "02"}]}),
        encoding="utf-8",
    )
    (root / "extracted" / "scope_metadata.json").write_text(
        json.dumps({"brand": "Dutch Bros", "brand_mismatch_warning": "Taco Bell vs Dutch Bros"}),
        encoding="utf-8",
    )
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"lines": [{"cost": 1.0}, {"cost": None}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths_mod, "storage_root", lambda: tmp_path)
    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / s)
    monkeypatch.setattr(pipeline_context, "storage_root", lambda: tmp_path)

    payload = pipeline_context.write_context(slug)
    assert payload["door_count"] == 2
    assert payload["brand_from_pdf"] == "Dutch Bros"
    assert payload["priced_count"] == 1
    assert "extracted/line_items.json" in payload["artifacts"]
    block = pipeline_context.prompt_block(slug)
    assert "Pipeline context" in block
    assert "Dutch Bros" in block
