"""Object-storage backends behind the Path-based storage façade.

STORAGE_BACKEND=local (default): disk under STORAGE_ROOT only.
STORAGE_BACKEND=s3: put/get via boto3; workers still hydrate into STORAGE_ROOT
so pdfplumber / Claude / sandbox keep real paths.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

from cbc.shared.config import settings

log = logging.getLogger("cbc.storage_backends")


class StorageBackend(Protocol):
    def put_file(self, local: Path, key: str) -> None: ...

    def get_file(self, key: str, local: Path) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class LocalBackend:
    """No remote store — the on-disk tree is the source of truth."""

    def put_file(self, local: Path, key: str) -> None:
        return None

    def get_file(self, key: str, local: Path) -> None:
        return None

    def delete_prefix(self, prefix: str) -> None:
        return None

    def exists(self, key: str) -> bool:
        return False


class S3Backend:
    def __init__(self) -> None:
        import boto3

        self.bucket = os.environ.get("S3_BUCKET", "").strip()
        if not self.bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        kwargs: dict = {"region_name": os.environ.get("S3_REGION", "us-east-1")}
        endpoint = os.environ.get("S3_ENDPOINT_URL", "").strip()
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self._client = boto3.client("s3", **kwargs)

    def put_file(self, local: Path, key: str) -> None:
        self._client.upload_file(str(local), self.bucket, key)

    def get_file(self, key: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self.bucket, key, str(local))

    def delete_prefix(self, prefix: str) -> None:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": item["Key"]} for item in page.get("Contents") or []]
            if objects:
                self._client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": objects}
                )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


_backend: StorageBackend | None = None


def backend_name() -> str:
    return os.environ.get("STORAGE_BACKEND", "local").strip().lower() or "local"


def get_backend() -> StorageBackend:
    global _backend
    if _backend is not None:
        return _backend
    name = backend_name()
    if name == "s3":
        _backend = S3Backend()
    else:
        _backend = LocalBackend()
    return _backend


def reset_backend() -> None:
    """Test helper — drop the cached backend instance."""
    global _backend
    _backend = None


def object_key_for(local: Path) -> str | None:
    """Map a path under STORAGE_ROOT or PRICEBOOK_DIR to an object key."""
    resolved = Path(local).resolve()
    for root, prefix in (
        (settings.storage_root.resolve(), "projects"),
        (settings.pricebook_dir.resolve(), "pricebooks"),
    ):
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        return f"{prefix}/{rel}"
    return None


def after_local_write(local: Path) -> None:
    """Push a freshly written local file to the durable backend."""
    key = object_key_for(local)
    if not key:
        return
    get_backend().put_file(Path(local), key)


def ensure_local(local: Path, *, key: str | None = None) -> Path:
    """Hydrate `local` from the backend when missing on disk."""
    path = Path(local)
    if path.is_file():
        return path
    object_key = key or object_key_for(path)
    if not object_key:
        return path
    backend = get_backend()
    if backend_name() == "local":
        return path
    if not backend.exists(object_key):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    backend.get_file(object_key, path)
    return path


def hydrate_project(slug: str) -> Path:
    """Ensure the project tree exists locally (download from S3 when needed)."""
    root = settings.storage_root / slug
    if backend_name() == "local":
        return root
    backend = get_backend()
    prefix = f"projects/{slug}/"
    # List via exists of common dirs is insufficient; download known layout by
    # walking S3 keys under the prefix when the client supports list.
    try:
        client = getattr(backend, "_client", None)
        bucket = getattr(backend, "bucket", None)
        if client is None or bucket is None:
            return root
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents") or []:
                key = item["Key"]
                rel = key[len("projects/") :]
                target = settings.storage_root / rel
                if target.is_file():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                backend.get_file(key, target)
    except Exception:
        log.exception("hydrate_project failed for %s", slug)
    return root


def push_paths(local_paths: list[Path]) -> None:
    for path in local_paths:
        after_local_write(path)


def purge_remote_project(slug: str) -> None:
    if backend_name() == "local":
        return
    get_backend().delete_prefix(f"projects/{slug}/")
