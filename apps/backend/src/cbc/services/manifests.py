"""Sidecar manifests next to live artifacts (audit B-13).

A write records what produced the file and which inputs it depended on. After a
passing validation check the sidecar is stamped. Reuse is allowed only when every
listed dependency hash still matches and validation passed. No TTL.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.core.paths import repo_root

ROOT = repo_root()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def live_path(project: str, relative: str) -> Path:
    return ROOT / "projects" / project / relative


def sidecar_path(project: str, relative: str) -> Path:
    live = live_path(project, relative)
    return live.parent / f"{live.name}.manifest.json"


def _raw_inputs(project: str) -> dict[str, str]:
    raw = ROOT / "projects" / project / "uploads" / "raw"
    if not raw.is_dir():
        return {}
    return {
        f"uploads/raw/{pdf.name}": _sha256_file(pdf)
        for pdf in sorted(raw.glob("*"))
        if pdf.is_file()
    }


def write_sidecar(
    project: str,
    relative: str,
    artifact_sha256: str,
    *,
    produced_by: str = "save_artifact",
    extra_inputs: dict[str, str] | None = None,
) -> Path:
    """Write `<path>.manifest.json` beside the live artifact."""
    inputs: dict[str, str] = {}
    if relative.startswith("extracted/") or relative.startswith("priced/"):
        inputs.update(_raw_inputs(project))
    if extra_inputs:
        inputs.update(extra_inputs)
    payload = {
        "artifact": relative,
        "artifactSha256": artifact_sha256,
        "producedBy": produced_by,
        "producedAt": _now(),
        "inputs": inputs,
        "dependencies": dict(inputs),
        "validation": {"passed": False},
    }
    target = sidecar_path(project, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def stamp_validation(
    project: str, relative: str, *, checked_by: str = "worker"
) -> dict[str, Any] | None:
    """Record a passing check on an existing sidecar. No-op if the file moved."""
    target = sidecar_path(project, relative)
    live = live_path(project, relative)
    if not target.is_file() or not live.is_file():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("artifactSha256") != _sha256_file(live):
        return None
    data["validation"] = {
        "passed": True,
        "checkedBy": checked_by,
        "checkedAt": _now(),
    }
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def stamp_phase(project: str, phase_state: dict[str, Any]) -> None:
    for entry in (phase_state or {}).values():
        if not isinstance(entry, dict) or not entry.get("passed"):
            continue
        for relative in (entry.get("artifacts") or {}):
            stamp_validation(project, relative)


def reuse_ok(project: str, relative: str) -> bool:
    """True only when the sidecar exists, validation passed, and deps still match."""
    target = sidecar_path(project, relative)
    live = live_path(project, relative)
    if not target.is_file() or not live.is_file():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not (data.get("validation") or {}).get("passed"):
        return False
    if data.get("artifactSha256") != _sha256_file(live):
        return False
    for dep_rel, sha in (data.get("dependencies") or {}).items():
        path = live_path(project, dep_rel)
        if not path.is_file() or _sha256_file(path) != sha:
            return False
    return True


def reusable_phases(project: str, phase_state: dict[str, Any] | None) -> dict[str, Any]:
    """Keep phases whose recorded artifact SHAs still match disk (and sidecars, if any)."""
    kept: dict[str, Any] = {}
    for name, entry in (phase_state or {}).items():
        if not isinstance(entry, dict) or not entry.get("passed"):
            continue
        artifacts = entry.get("artifacts") or {}
        if not artifacts:
            continue
        ok = True
        for relative, sha in artifacts.items():
            path = live_path(project, relative)
            if not path.is_file() or _sha256_file(path) != sha:
                ok = False
                break
            sidecar = sidecar_path(project, relative)
            if sidecar.is_file() and not reuse_ok(project, relative):
                ok = False
                break
        if ok:
            kept[name] = entry
    return kept
