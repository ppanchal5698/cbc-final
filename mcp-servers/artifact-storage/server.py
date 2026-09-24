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
    """CBC_PROJECTS_ROOT (a sandboxed run's clone), else STORAGE_ROOT, else the default.

    One definition, cbc.shared.paths.storage_root(). This kept its own fallback to
    ROOT/projects while the manifests it writes followed the storage root, so a
    save landed in one directory and its sidecar in another.
    """
    from cbc.shared.paths import storage_root

    return storage_root().resolve()


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


def _assert_writable(path: str) -> None:
    """The write allowlist, for every caller that reaches the tree.

    `propose_patch` used to skip this: it went straight to `_resolve` and
    `read_text`, so a path the write gate would refuse came back as a decode
    error or a missing-file message instead of the refusal it is. One guard,
    both callers - `uploads/` is the worker's and stays unwritable from here.
    """
    posix = path.replace("\\", "/").lstrip("/")
    if ".." in posix.split("/") or not SAVE_ALLOW.match(posix):
        raise ValueError(
            f"refusing to write {path!r} — allowed paths are extracted/*.json, "
            "priced/*.json, review/*.(json|html|md), quotation.html"
        )


# A placeholder is any body that is only a content-substitution token. Exact
# matching on three literals let `{FILE_CONTENT}`, `{{ content }}` and every
# truncation marker through, and the file landed with the token as its content.
_PLACEHOLDER = re.compile(r"^\{{0,2}\s*<?\s*[a-z_-]*file[_-]?contents?\s*>?\s*\}{0,2}$", re.I)
_BARE_CONTENT = re.compile(r"^\{{1,2}\s*contents?\s*\}{1,2}$", re.I)


def _assert_not_placeholder(path: str, stripped: str) -> None:
    if _PLACEHOLDER.match(stripped) or _BARE_CONTENT.match(stripped):
        raise ValueError(
            f"refusing placeholder content for {path!r} - read the file from disk first"
        )
    # A draft or a rendered page that is one short line is a truncation marker
    # ("...", "[content]", "TODO"), not a deliverable.
    if path.endswith(("_draft.md", ".html")) and "\n" not in stripped and len(stripped) < 40:
        raise ValueError(
            f"refusing {len(stripped)}-byte single-line content for {path!r} - "
            "this is a truncation marker, not the artifact"
        )


def save_artifact(
    project: str, path: str, content: str, version_note: str | None = None
) -> dict[str, Any]:
    _assert_writable(path)
    stripped = content.strip()
    _assert_not_placeholder(path, stripped)
    if path.endswith("quotation.html") and len(stripped) < 200:
        raise ValueError(
            f"refusing to save quotation.html with only {len(stripped)} bytes - "
            "run validate_and_render_quote.py and Read the file before save_artifact"
        )

    # Schema gate for extract checkpoints (Claude Code has no Messages json_schema).
    # Normalize known LLM shape mistakes (page_size array, thickness→notes) first,
    # then persist the cleaned payload so disk matches what validators accept.
    # This import is deliberately unguarded. It used to sit under
    # `except ImportError: pass`, which meant that if `artifact_schema` alone
    # failed to import - a missing pydantic in the MCP subprocess is enough,
    # while `cbc.shared` below still resolves - the gate vanished and every
    # malformed checkpoint landed on disk reporting success. A validator that
    # can disappear without saying so is worse than no validator, because the
    # run looks clean. If this cannot import, the write must fail.
    from cbc.modules.extraction.api.artifact_schema import PATH_SCHEMAS, prepare_artifact_text

    posix_key = path.replace("\\", "/")
    if posix_key in PATH_SCHEMAS:
        content, problems = prepare_artifact_text(posix_key, content)
        if problems:
            raise ValueError("; ".join(problems))

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


def _window(content: str, start: int, max_chars: int) -> dict[str, Any]:
    """A slice of the artifact, saying plainly how much was left behind.

    Truncation that does not announce itself is worse than refusing: an agent
    reads half a JSON document, parses what it got, and reports on a schedule
    that stops mid-array.
    """
    try:
        begin = max(0, int(start))
    except (TypeError, ValueError):
        begin = 0
    try:
        budget = max(1_000, min(int(max_chars), MAX_CHARS_CEILING))
    except (TypeError, ValueError):
        budget = DEFAULT_MAX_CHARS
    chunk = content[begin : begin + budget]
    nxt = begin + len(chunk)
    out: dict[str, Any] = {
        "content": chunk,
        "start": begin,
        "total_chars": len(content),
        "next": nxt if nxt < len(content) else None,
    }
    if out["next"] is not None:
        out["note"] = (
            f"{len(content) - nxt} characters not returned. Call again with "
            f"start={nxt} to continue, or raise max_chars (ceiling "
            f"{MAX_CHARS_CEILING}). This is a slice, not the whole file - do not "
            "parse it as complete JSON."
        )
    return out


# One artifact read must not be able to blow the caller's context. `_sheetmap.json`
# on an 87-page set is 58,370 characters; an agent asking for it got the whole
# thing refused by the harness and fell back to shelling out with `find` and
# `python3` to read its own artifact. Same shape as `bid-docs.get_page_blocks`.
DEFAULT_MAX_CHARS = 20_000
MAX_CHARS_CEILING = 200_000


def get_artifact(
    project: str,
    path: str,
    version: str | None = None,
    start: int = 0,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
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
            **_window(blob.read_text(encoding="utf-8"), start, max_chars),
        }

    target = _resolve(project, path)
    if not target.exists():
        raise FileNotFoundError(f"{path} not found in project {project}")
    content = target.read_text(encoding="utf-8")
    return {
        "project": project,
        "path": path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        **_window(content, start, max_chars),
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


def propose_patch(
    project: str, path: str, patches: list[dict[str, Any]], version_note: str | None = None
) -> dict[str, Any]:
    """Change named fields of an artifact Python already owns.

    Whole-file authorship is what made one bad key cost a whole run. Here the
    deterministic seed on disk is the base, each patch is validated on its own,
    and a patch that fails costs that field and leaves a review flag.

    The write goes through `save_artifact`, so the schema gate and the SHA-256
    version history apply exactly as they do to any other write.
    """
    from cbc.modules.extraction.api.patching import apply_patches, summarise

    if not isinstance(patches, list) or not patches:
        raise ValueError("patches must be a non-empty list")

    # Before the read, not after: a path the write gate refuses must say so,
    # rather than surfacing as "does not exist yet" or a UnicodeDecodeError.
    _assert_writable(path)
    target = _resolve(project, path)
    if not target.is_file():
        raise ValueError(
            f"{path!r} does not exist yet - propose_patch edits the seeded artifact, "
            "it does not create one"
        )
    payload = json.loads(target.read_text(encoding="utf-8"))
    updated, results = apply_patches(payload, patches)
    summary = summarise(results)

    # Nothing held: say so and leave the file alone rather than rewriting it
    # byte-identically and reporting a version that means nothing.
    if summary["applied"]:
        saved = save_artifact(
            project,
            path,
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
            version_note or f"patch: {summary['applied']} applied, {summary['rejected']} rejected",
        )
        summary["sha256"] = saved["sha256"]
    summary["path"] = path
    return summary


HANDLERS = {
    "save_artifact": save_artifact,
    "propose_patch": propose_patch,
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

        # Placeholders. Exact matching on three literals let every other
        # spelling through, and the token landed on disk as the artifact.
        for body in ("{file_content}", "{FILE_CONTENT}", "{{ content }}",
                     "<FILE_CONTENTS>", "{ file_contents }"):
            try:
                save_artifact(project, "review/x_draft.md", body)
            except ValueError:
                pass
            else:  # pragma: no cover
                raise AssertionError(f"placeholder {body!r} was not blocked")
        # ...while a real body that merely mentions the word still saves.
        save_artifact(project, "review/x_draft.md", '{"content": "a real draft"}\nmore')

        # `uploads/` is the worker's. propose_patch must refuse it at the gate,
        # not by failing to read it.
        for tool in (
            lambda: save_artifact(project, "uploads/final/quotation.pdf", "x" * 80),
            lambda: propose_patch(project, "uploads/final/x.json", [{"path": "a/b/c", "value": 1}]),
        ):
            try:
                tool()
            except ValueError as exc:
                assert "refusing to write" in str(exc), exc
            else:  # pragma: no cover
                raise AssertionError("uploads/ was writable")

        # propose_patch: the good field lands, the invented one costs itself.
        seed = {"source_page": 16, "openings": [
            {"door_number": "05", "size": "3068", "handing": None,
             "source_page": 16, "flags": []},
        ]}
        save_artifact(project, "extracted/line_items.json", json.dumps(seed), "seed")
        cite = {"source_page": 16, "excerpt": "05 UNISEX WRM RH"}
        patched = propose_patch(project, "extracted/line_items.json", [
            {"op": "set", "path": "openings/05/handing", "value": "RH", "evidence": cite},
            {"op": "set", "path": "openings/05/thickness", "value": "1 3/4in", "evidence": cite},
        ])
        assert patched["applied"] == 1 and patched["rejected"] == 1, patched
        on_disk = json.loads(
            get_artifact(project, "extracted/line_items.json")["content"]
        )["openings"][0]
        assert on_disk["handing"] == "RH", on_disk
        assert "thickness" not in on_disk, "an invented key must not reach disk"
        assert "patch_rejected_thickness" in on_disk["flags"], on_disk
        # The write went through save_artifact, so it is versioned like any other.
        assert list_versions(project, "extracted/line_items.json")["version_count"] == 2

        # Nothing applies: the file is left alone rather than re-versioned.
        before = get_artifact(project, "extracted/line_items.json")["content"]
        none_held = propose_patch(project, "extracted/line_items.json", [
            {"op": "set", "path": "openings/99/handing", "value": "LH", "evidence": cite},
        ])
        assert none_held["applied"] == 0 and none_held["run_can_continue"] is True
        assert get_artifact(project, "extracted/line_items.json")["content"] == before
    finally:
        shutil.rmtree(_projects_root() / project, ignore_errors=True)
    print("artifact-storage demo OK")


if __name__ == "__main__":
    serve("artifact-storage", TOOLS, HANDLERS, demo=_demo)
