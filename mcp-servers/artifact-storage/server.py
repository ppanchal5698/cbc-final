#!/usr/bin/env python3
"""artifact-storage MCP server - project file writes with version history.

Every write is content-addressed by SHA-256 and recorded in an append-only index,
so "what did the previous run produce for this opening?" is always answerable
(NFR-3, .claude/rules/auditability.md).

Writes are confined to projects/{project}/ (.claude/rules/file-safety.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _runtime import serve
from tools import TOOLS

ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIRNAME = ".versions"
INDEX_NAME = "versions.jsonl"

SAVE_ALLOW = re.compile(
    r"^(extracted|priced|review)/[A-Za-z0-9._-]+\.(json|html|md)$|^quotation\.html$"
)


def _projects_root() -> Path:
    override = os.environ.get("CBC_PROJECTS_ROOT")
    if override:
        return Path(override).resolve()
    storage = os.environ.get("STORAGE_ROOT")
    if storage:
        return Path(storage).resolve()
    return ROOT / "projects"


def _project_dir(project: str) -> Path:
    base = _projects_root()
    directory = (base / project).resolve()
    if base.resolve() not in directory.parents and directory != base.resolve():
        raise ValueError(f"refusing to leave projects/: {project!r}")
    return directory


def _resolve(project: str, path: str) -> Path:
    base = _project_dir(project)
    target = (base / path).resolve()
    if base not in target.parents:
        raise ValueError(f"refusing to write outside projects/{project}/: {path!r}")
    return target


def _versions_dir(project: str) -> Path:
    return _project_dir(project) / VERSIONS_DIRNAME


def save_artifact(
    project: str, path: str, content: str, version_note: str | None = None
) -> dict[str, Any]:
    posix = path.replace("\\", "/").lstrip("/")
    if ".." in posix.split("/") or not SAVE_ALLOW.match(posix):
        raise ValueError(
            f"refusing to write {path!r} — allowed paths are extracted/*.json, "
            "priced/*.json, review/*.(json|html|md), quotation.html"
        )
    stripped = content.strip()
    if stripped in ("{file_content}", "{content}", "<file_content>"):
        raise ValueError(
            f"refusing placeholder content for {path!r} - read the file from disk first"
        )
    if path.endswith("quotation.html") and len(stripped) < 200:
        raise ValueError(
            f"refusing to save quotation.html with only {len(stripped)} bytes - "
            "run validate_and_render_quote.py and Read the file before save_artifact"
        )

    # Schema gate for extract checkpoints (Claude Code has no Messages json_schema).
    try:
        from cbc.modules.extraction.api.artifact_schema import PATH_SCHEMAS, validate_artifact_text

        if path.replace("\\", "/") in PATH_SCHEMAS:
            problems = validate_artifact_text(path.replace("\\", "/"), content)
            if problems:
                raise ValueError("; ".join(problems))
    except ImportError:
        pass

    target = _resolve(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    previous = target.read_text(encoding="utf-8") if target.exists() else None
    unchanged = previous is not None and hashlib.sha256(previous.encode("utf-8")).hexdigest() == digest

    # Atomic replace so mid-run Ops-Hub sync never reads a truncated JSON write.
    from cbc.shared.storage import atomic_write_text

    atomic_write_text(target, content)

    from cbc.shared import manifests

    manifests.write_sidecar(project, path, digest)

    store = _versions_dir(project)
    store.mkdir(parents=True, exist_ok=True)
    if not unchanged:
        atomic_write_text(store / digest, content)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": path,
            "sha256": digest,
            "bytes": len(content.encode("utf-8")),
            "note": version_note,
        }
        with (store / INDEX_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    return {
        "project": project,
        "path": path,
        "absolute_path": str(target),
        "sha256": digest,
        "bytes": len(content.encode("utf-8")),
        "unchanged": unchanged,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


def get_artifact(project: str, path: str, version: str | None = None) -> dict[str, Any]:
    if version:
        store = _versions_dir(project)
        candidates = [p for p in store.glob(f"{version}*") if p.name != INDEX_NAME]
        if not candidates:
            raise FileNotFoundError(f"no stored version starting {version!r} for {path}")
        blob = candidates[0]
        return {
            "project": project,
            "path": path,
            "version": blob.name,
            "content": blob.read_text(encoding="utf-8"),
        }

    target = _resolve(project, path)
    if not target.exists():
        raise FileNotFoundError(f"{path} not found in project {project}")
    content = target.read_text(encoding="utf-8")
    return {
        "project": project,
        "path": path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def list_versions(project: str, path: str) -> dict[str, Any]:
    index = _versions_dir(project) / INDEX_NAME
    if not index.exists():
        return {"project": project, "path": path, "versions": []}
    records = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("path") == path:
            records.append(record)
    records.reverse()
    return {"project": project, "path": path, "version_count": len(records), "versions": records}


def list_project_files(project: str, subdir: str | None = None) -> dict[str, Any]:
    base = _project_dir(project)
    if not base.exists():
        raise FileNotFoundError(f"project {project} does not exist")
    root = (base / subdir).resolve() if subdir else base
    files = []
    for item in sorted(root.rglob("*")):
        if item.is_file() and VERSIONS_DIRNAME not in item.parts:
            files.append(
                {
                    "path": str(item.relative_to(base)).replace("\\", "/"),
                    "bytes": item.stat().st_size,
                }
            )
    return {"project": project, "root": str(root), "file_count": len(files), "files": files}


HANDLERS = {
    "save_artifact": save_artifact,
    "get_artifact": get_artifact,
    "list_versions": list_versions,
    "list_project_files": list_project_files,
}


def _demo() -> None:
    """Runnable check: versioning, round-trip, and the path-escape guard.

    Runs in a throwaway project so repeated runs stay deterministic and no demo
    records leak into a real project's version index.
    """
    import shutil

    project = "_selftest"
    shutil.rmtree(_projects_root() / project, ignore_errors=True)
    try:
        first = save_artifact(project, "review/demo.json", '{"v":1}', "demo v1")
        assert first["unchanged"] is False
        assert save_artifact(project, "review/demo.json", '{"v":1}')["unchanged"] is True
        save_artifact(project, "review/demo.json", '{"v":2}', "demo v2")

        assert json.loads(get_artifact(project, "review/demo.json")["content"])["v"] == 2
        assert list_versions(project, "review/demo.json")["version_count"] == 2
        old = get_artifact(project, "review/demo.json", version=first["sha256"][:8])
        assert json.loads(old["content"])["v"] == 1
        # save_artifact also writes <path>.manifest.json (B-13); .versions/ is excluded.
        listed = list_project_files(project)
        assert listed["file_count"] == 2
        assert {f["path"] for f in listed["files"]} == {
            "review/demo.json",
            "review/demo.json.manifest.json",
        }

        try:
            save_artifact(project, "../../pricebooks/evil.txt", "nope")
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("path escape was not blocked")
    finally:
        shutil.rmtree(_projects_root() / project, ignore_errors=True)
    print("artifact-storage demo OK")


if __name__ == "__main__":
    serve("artifact-storage", TOOLS, HANDLERS, demo=_demo)
