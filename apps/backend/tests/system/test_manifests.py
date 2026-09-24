"""B-13: artifact sidecars and reuse_ok."""
from __future__ import annotations

import hashlib
import json

from cbc.shared import manifests

from _runtime import load_server


def test_save_artifact_writes_sidecar_with_matching_sha(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manifests, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    art = load_server("artifact-storage")
    monkeypatch.setenv("CBC_PROJECTS_ROOT", str(tmp_path / "projects"))
    content = '{"openings": []}'
    art.save_artifact("demo", "extracted/line_items.json", content)
    sidecar = tmp_path / "projects" / "demo" / "extracted" / "line_items.json.manifest.json"
    assert sidecar.is_file()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["artifactSha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert data["artifact"] == "extracted/line_items.json"
    assert data["validation"]["passed"] is False


def test_reuse_ok_false_when_input_hash_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manifests, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    project = "demo"
    raw = tmp_path / "projects" / project / "uploads" / "raw"
    raw.mkdir(parents=True)
    source = raw / "set.pdf"
    source.write_bytes(b"%PDF-1.4 input-a")
    live = tmp_path / "projects" / project / "extracted" / "line_items.json"
    live.parent.mkdir(parents=True)
    live.write_text("{}", encoding="utf-8")
    sha = hashlib.sha256(b"{}").hexdigest()
    manifests.write_sidecar(project, "extracted/line_items.json", sha)
    manifests.stamp_validation(project, "extracted/line_items.json")
    assert manifests.reuse_ok(project, "extracted/line_items.json")
    source.write_bytes(b"%PDF-1.4 input-b")
    assert manifests.reuse_ok(project, "extracted/line_items.json") is False


def test_reuse_ok_false_when_sidecar_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manifests, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    live = tmp_path / "projects" / "demo" / "extracted" / "line_items.json"
    live.parent.mkdir(parents=True)
    live.write_text("{}", encoding="utf-8")
    assert manifests.reuse_ok("demo", "extracted/line_items.json") is False


def test_reusable_phases_drop_on_sha_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manifests, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    live = tmp_path / "projects" / "demo" / "extracted" / "line_items.json"
    live.parent.mkdir(parents=True)
    live.write_text("{}", encoding="utf-8")
    sha = hashlib.sha256(b"{}").hexdigest()
    kept = manifests.reusable_phases(
        "demo",
        {"extraction": {"passed": True, "artifacts": {"extracted/line_items.json": sha}}},
    )
    assert "extraction" in kept
    mismatch = manifests.reusable_phases(
        "demo",
        {
            "extraction": {
                "passed": True,
                "artifacts": {"extracted/line_items.json": "deadbeef"},
            }
        },
    )
    assert mismatch == {}
