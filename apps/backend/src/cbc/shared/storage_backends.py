"""Object-storage backends behind the Path-based storage façade.

STORAGE_BACKEND=local (default): disk under STORAGE_ROOT only.
STORAGE_BACKEND=azure: Azure Blob Storage (Floci-AZ locally); workers still
hydrate into STORAGE_ROOT so pdfplumber / Claude / sandbox keep real paths.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, Protocol

from cbc.shared.config import settings

log = logging.getLogger("cbc.storage_backends")


class StorageBackend(Protocol):
    def put_file(self, local: Path, key: str) -> None: ...

    def get_file(self, key: str, local: Path) -> None: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...

    def list_keys(self, prefix: str) -> Iterable[str]: ...


class LocalBackend:
    """No remote store — the on-disk tree is the source of truth."""

    def put_file(self, local: Path, key: str) -> None:
        return None

    def get_file(self, key: str, local: Path) -> None:
        return None

    def exists(self, key: str) -> bool:
        return False

    def delete(self, key: str) -> None:
        return None

    def delete_prefix(self, prefix: str) -> None:
        return None

    def list_keys(self, prefix: str) -> Iterable[str]:
        return ()


class AzureBlobBackend:
    """One container; keys are `projects/...` and `pricebooks/...`.

    AZURE_STORAGE_CONNECTION_STRING is the only thing that differs between
    Floci-AZ and a real storage account.
    """

    def __init__(self) -> None:
        from azure.core.exceptions import HttpResponseError, ResourceExistsError
        from azure.storage.blob import BlobServiceClient

        connection = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        if not connection:
            raise RuntimeError("STORAGE_BACKEND=azure requires AZURE_STORAGE_CONNECTION_STRING")
        name = os.environ.get("AZURE_STORAGE_CONTAINER", "").strip() or "cbc"
        # Bounded, so a store that is down fails a push in seconds, not minutes.
        kwargs: dict = {"retry_total": 3}
        # Floci serves TLS with a self-signed certificate. Trusting that one PEM
        # keeps verification on; a real account leaves this unset and uses the
        # system trust store.
        ca = os.environ.get("AZURE_EMULATOR_CA", "").strip()
        if ca:
            kwargs["connection_verify"] = ca
        service = BlobServiceClient.from_connection_string(connection, **kwargs)
        self._container = service.get_container_client(name)
        try:
            self._container.create_container()
        except ResourceExistsError:
            pass
        except HttpResponseError as exc:
            # A container-scoped SAS cannot create containers; production
            # provisions this one. Anything else is a real misconfiguration.
            if exc.status_code != 403:
                raise

    def put_file(self, local: Path, key: str) -> None:
        with Path(local).open("rb") as handle:
            self._container.upload_blob(key, handle, overwrite=True)

    def get_file(self, key: str, local: Path) -> None:
        # A reader sees the old file or the whole new one, never half a download.
        local.parent.mkdir(parents=True, exist_ok=True)
        partial = local.with_name(f".{local.name}.part")
        try:
            with partial.open("wb") as handle:
                self._container.download_blob(key).readinto(handle)
            os.replace(partial, local)
        finally:
            partial.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._container.get_blob_client(key).exists()

    def delete(self, key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._container.delete_blob(key)
        except ResourceNotFoundError:
            pass

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self.list_keys(prefix)):
            self.delete(key)

    def list_keys(self, prefix: str) -> Iterable[str]:
        return self._container.list_blob_names(name_starts_with=prefix)


_BACKENDS = {"local": LocalBackend, "azure": AzureBlobBackend}
_backend: StorageBackend | None = None


def backend_name() -> str:
    return os.environ.get("STORAGE_BACKEND", "local").strip().lower() or "local"


def get_backend() -> StorageBackend:
    global _backend
    if _backend is None:
        name = backend_name()
        if name not in _BACKENDS:
            # A typo used to fall back to local quietly, with every remote code
            # path still switched on and nothing ever reaching the store.
            raise RuntimeError(f"STORAGE_BACKEND={name!r} is not one of {sorted(_BACKENDS)}")
        _backend = _BACKENDS[name]()
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
    """Ensure the project tree exists locally (download from the store when needed)."""
    root = settings.storage_root / slug
    if backend_name() == "local":
        return root
    try:
        backend = get_backend()
        for key in backend.list_keys(f"projects/{slug}/"):
            target = settings.storage_root / key[len("projects/") :]
            if target.is_file():
                continue
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
