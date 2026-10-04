"""Claude's page triage survives the sheetmap rebuild and reaches role lookups."""
from __future__ import annotations

import json
from pathlib import Path

from cbc.modules.extraction.infrastructure import sheetmap


def _sheetmap_payload(path: str = "projects/x/uploads/raw/set.pdf") -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00Z",
        "files": [
            {
                "path": path,
                "pages": [
                    {"source_page": 4, "roles": ["floor_plan"], "kind": "ranked"},
                    {"source_page": 19, "roles": [], "kind": "ranked"},
                ],
            }
        ],
    }


def _write_triage(root: Path, slug: str, path: str) -> None:
    target = root / slug / sheetmap.TRIAGE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "pages": {
                    f"{path}#19": {"roles": ["door_schedule"], "alternate": "Alternate 1"},
                }
            }
        ),
        encoding="utf-8",
    )


def test_triage_roles_are_found_by_role_lookup(tmp_path, monkeypatch):
    """A page only Claude identified still answers pages_for_roles.

    Triage exists for the page the term heuristics miss. If the lookup every
    consumer uses ignored the sidecar, the whole pass would be decorative.
    """
    monkeypatch.setattr(sheetmap, "storage_root", lambda: tmp_path)
    path = "projects/x/uploads/raw/set.pdf"
    _write_triage(tmp_path, "x", path)

    payload = sheetmap._apply_triage("x", _sheetmap_payload(path))
    hits = sheetmap.pages_for_roles(payload, "door_schedule")

    assert [h["source_page"] for h in hits] == [19]
    assert "door_schedule" in hits[0]["roles"]
    # The derived role on another page is untouched.
    assert [h["source_page"] for h in sheetmap.pages_for_roles(payload, "floor_plan")] == [4]


def test_triage_is_reapplied_and_never_goes_stale(tmp_path, monkeypatch):
    """Re-running triage replaces its roles rather than accumulating them.

    `roles` stays exactly what the deterministic pass derived and `triage_roles`
    is rewritten from the sidecar on every build, so a corrected triage cannot
    leave its previous answer behind in the artifact.
    """
    monkeypatch.setattr(sheetmap, "storage_root", lambda: tmp_path)
    path = "projects/x/uploads/raw/set.pdf"
    _write_triage(tmp_path, "x", path)

    payload = sheetmap._apply_triage("x", _sheetmap_payload(path))
    page19 = payload["files"][0]["pages"][1]
    assert page19["triage_roles"] == ["door_schedule"]
    assert page19["alternate"] == "Alternate 1"
    assert page19["roles"] == [], "derived roles must not be polluted by triage"

    # Triage re-runs and corrects itself: page 19 was really the finish schedule.
    (tmp_path / "x" / sheetmap.TRIAGE_REL).write_text(
        json.dumps({"pages": {f"{path}#19": {"roles": ["finish"]}}}), encoding="utf-8"
    )
    payload = sheetmap._apply_triage("x", _sheetmap_payload(path))
    assert payload["files"][0]["pages"][1]["triage_roles"] == ["finish"]
    assert sheetmap.pages_for_roles(payload, "door_schedule") == []


def test_missing_or_corrupt_triage_is_not_fatal(tmp_path, monkeypatch):
    """No triage, or a half-written one, leaves the deterministic map intact."""
    monkeypatch.setattr(sheetmap, "storage_root", lambda: tmp_path)
    assert sheetmap.load_triage("x") == {}

    payload = sheetmap._apply_triage("x", _sheetmap_payload())
    assert [h["source_page"] for h in sheetmap.pages_for_roles(payload, "floor_plan")] == [4]

    target = tmp_path / "x" / sheetmap.TRIAGE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"pages": {"a": ', encoding="utf-8")  # truncated write
    assert sheetmap.load_triage("x") == {}
    payload = sheetmap._apply_triage("x", _sheetmap_payload())
    assert [h["source_page"] for h in sheetmap.pages_for_roles(payload, "floor_plan")] == [4]
