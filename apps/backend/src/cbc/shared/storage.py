"""Project file layout on disk.

Mongo holds the structured data; the PDFs stay on the filesystem in the layout
the existing Python skills already expect - `projects/{slug}/uploads/raw/` and so
on. pdfplumber and PyMuPDF want real paths, and keeping this layout means every
agent and skill keeps working unchanged.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.shared.config import settings

SUBDIRS = (
    "uploads/raw",
    "uploads/processed",
    "uploads/final",
    "extracted",
    "priced",
    "review",
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Lowercase, underscore-separated, ascii - matches the existing project names."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("_", ascii_name.lower()).strip("_")
    return slug[:60] or "project"


def project_dir(slug: str) -> Path:
    return settings.storage_root / slug


def purge_project(slug: str) -> None:
    """Remove a project's entire directory tree from disk.

    Human-initiated via the admin delete route — not something a pipeline agent
    does during a run. Idempotent when the folder is already gone.
    """
    if not slug or not slug.strip():
        raise ValueError("refusing to purge an empty project slug")

    root = project_dir(slug).resolve()
    storage_root = settings.storage_root.resolve()
    if root == storage_root:
        raise ValueError(f"refusing to delete the storage root: {storage_root}")
    if not root.is_relative_to(storage_root):
        raise ValueError(f"refusing to delete outside storage root: {root}")

    if root.exists():
        shutil.rmtree(root)
    try:
        from cbc.shared.storage_backends import purge_remote_project

        purge_remote_project(slug)
    except Exception:
        pass


def scaffold(slug: str) -> Path:
    """Create the project tree. Idempotent - safe to call on an existing project."""
    root = project_dir(slug)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    trail = root / "audit_trail.jsonl"
    if not trail.exists():
        trail.touch()
    return root


def raw_dir(slug: str) -> Path:
    return project_dir(slug) / "uploads" / "raw"


def safe_name(filename: str) -> str:
    """Reduce an uploaded filename to a bare name that cannot escape its directory.

    `UploadFile.filename` is whatever the client put in Content-Disposition, and
    nothing upstream strips it: `directory / "../../.claude/hooks/x.py"` resolves
    outside the project tree and `write_bytes` follows it. Both separators are
    normalised because a Windows-shaped path is only a separator on one platform
    and a very odd filename on the other.
    """
    name = os.path.basename(filename.replace("\\", "/")).strip()
    # A name that is only dots addresses a directory, not a file.
    return name if name.strip(".") else ""


def unique_filename(directory: Path, filename: str) -> Path:
    """Never overwrite an uploaded document - raw uploads are immutable."""
    target = directory / (safe_name(filename) or "upload")
    # Belt and braces: the basename above is what makes this true, and an assert
    # is what keeps it true if someone edits it.
    if not target.resolve().is_relative_to(directory.resolve()):
        raise ValueError(f"refusing to write outside {directory}: {filename!r}")
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return directory / f"{stem}_{stamp}{suffix}"


CHUNK = 1 << 20  # 1 MiB


async def receive_upload(file, target: Path, limit: int, magic: bytes | None = None) -> int:
    """Stream an upload to `target`, stopping the moment it exceeds `limit`.

    `await file.read()` with no argument pulls the whole body into memory before
    anything can check its size, so the 413 for a 2 GB POST arrived only after the
    process had already tried to hold 2 GB - or been OOM-killed, taking every
    in-flight request with it. Reading in chunks bounds the memory and yields the
    event loop between them.

    Returns the number of bytes written; raises ValueError on a body that is too
    large or does not start with `magic`, having removed the partial file.
    After a successful write, an optional malware scan runs; infected files are
    unlinked and raise ValueError so callers map them to 422.
    """
    size = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(CHUNK):
                if size == 0 and magic and not chunk.startswith(magic):
                    raise ValueError("only PDF bid documents are accepted")
                size += len(chunk)
                if size > limit:
                    raise ValueError(f"file exceeds {limit // (1024 * 1024)} MB")
                handle.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("the uploaded file is empty")

    from cbc.shared import malware

    try:
        malware.scan_file(target)
    except malware.MalwareDetected as exc:
        target.unlink(missing_ok=True)
        raise ValueError(str(exc)) from exc
    except malware.MalwareScanUnavailable as exc:
        target.unlink(missing_ok=True)
        raise ValueError(str(exc)) from exc

    # Durable copy for optional object storage (no-op when STORAGE_BACKEND=local).
    try:
        from cbc.shared.storage_backends import after_local_write

        after_local_write(target)
    except Exception:
        # Backend sync must not leave a half-accepted upload that jobs will claim.
        target.unlink(missing_ok=True)
        raise

    return size


def content_sha256(path: Path | str) -> str:
    """SHA-256 hex digest of file bytes (bid / price-book content identity)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path | str) -> str:
    """Store repo-relative paths so the database is portable across machines."""
    path = Path(path)
    try:
        return path.resolve().relative_to(settings.repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def absolute(stored: str) -> Path:
    path = Path(stored)
    resolved = path if path.is_absolute() else (settings.repo_root / path).resolve()
    try:
        from cbc.shared.storage_backends import ensure_local

        return ensure_local(resolved)
    except Exception:
        return resolved


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write through a temp file + os.replace so readers never see a torn file.

    Mid-run watchers sync `scope_metadata.json` as soon as it appears; a plain
    truncate-and-write can be read half-finished and fail JSON parse (or worse,
    import a truncated object).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically write a JSON document with trailing newline."""
    atomic_write_text(path, json.dumps(payload, indent=2, default=str) + "\n")
