"""W3c: a partially-failed wave promotes only its succeeded legs' artifacts.

`promote(slug, only=...)` restricts which allowlisted artifacts reach the live
bid, so one failed FRP leg does not discard a finished take-off. The audit trail
and the content-addressed version copies always promote regardless - they are the
whole run's history, not any one leg's.
"""
from __future__ import annotations

from cbc.shared.config import settings
from cbc.worker_kit import sandbox


def _seed_clone(tmp_path):
    slug = "demo"
    (tmp_path / slug / "extracted").mkdir(parents=True, exist_ok=True)
    workspace = sandbox.prepare(slug)
    clone = workspace / "projects" / slug
    (clone / "extracted").mkdir(parents=True, exist_ok=True)
    (clone / "extracted" / "line_items.json").write_text('{"openings": []}', encoding="utf-8")
    (clone / "extracted" / "frp_takeoff.json").write_text('{"fresh": true}', encoding="utf-8")
    (clone / "extracted" / "div10_takeoff.json").write_text('{"items": []}', encoding="utf-8")
    return slug, clone


def test_only_promotes_the_named_artifacts(tmp_path) -> None:
    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug, _clone = _seed_clone(tmp_path)
        promoted = sandbox.promote(
            slug,
            only={"extracted/line_items.json", "extracted/div10_takeoff.json"},
        )
        live = tmp_path / slug / "extracted"
        assert (live / "line_items.json").is_file()
        assert (live / "div10_takeoff.json").is_file()
        assert not (live / "frp_takeoff.json").exists(), "the failed leg must not promote"
        assert "extracted/frp_takeoff.json" not in promoted
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous


def test_only_none_promotes_every_artifact(tmp_path) -> None:
    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug, _clone = _seed_clone(tmp_path)
        sandbox.promote(slug)
        live = tmp_path / slug / "extracted"
        assert (live / "line_items.json").is_file()
        assert (live / "frp_takeoff.json").is_file()
        assert (live / "div10_takeoff.json").is_file()
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous


def test_append_only_and_version_copies_ignore_the_only_filter(tmp_path) -> None:
    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug, clone = _seed_clone(tmp_path)
        (clone / "audit_trail.jsonl").write_text('{"tool":"Read"}\n', encoding="utf-8")
        versions = clone / ".versions"
        versions.mkdir(parents=True, exist_ok=True)
        sha = "a" * 64
        (versions / sha).write_text("content", encoding="utf-8")

        # only=set(): no allowlisted artifact may promote, but history still must.
        sandbox.promote(slug, only=set())
        live = tmp_path / slug
        assert (live / "audit_trail.jsonl").is_file(), "append-only history always promotes"
        assert (live / ".versions" / sha).is_file(), "version copies always promote"
        assert not (live / "extracted" / "line_items.json").exists()
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous
