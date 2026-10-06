"""Malware scan and object-storage façade tests (no live ClamAV; Floci-AZ if it is up)."""
from __future__ import annotations

import os
import socket
import ssl
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from cbc.shared import malware, storage_backends


def test_malware_scan_off_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MALWARE_SCAN", "off")
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4 hello")
    malware.scan_file(path)


def test_malware_detected_from_clamd_response(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MALWARE_SCAN", "clamd")
    monkeypatch.setenv("MALWARE_SCAN_REQUIRED", "1")
    path = tmp_path / "eicar.pdf"
    path.write_bytes(b"%PDF-1.4 EICAR")

    def fake_instream(target, host, port, chunk_size=1 << 20):
        return "stream: Eicar-Test-Signature FOUND"

    monkeypatch.setattr(malware, "_instream", fake_instream)
    with pytest.raises(malware.MalwareDetected):
        malware.scan_file(path)


def test_clamd_down_soft_fails_unless_required(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MALWARE_SCAN", "clamd")
    monkeypatch.setenv("MALWARE_SCAN_REQUIRED", "0")
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4")

    def boom(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(malware, "_instream", boom)
    malware.scan_file(path)

    monkeypatch.setenv("MALWARE_SCAN_REQUIRED", "1")
    with pytest.raises(malware.MalwareScanUnavailable):
        malware.scan_file(path)


class _FakeBackend:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_file(self, local: Path, key: str) -> None:
        self.objects[key] = Path(local).read_bytes()

    def get_file(self, key: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.objects[key])

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self.list_keys(prefix)):
            del self.objects[key]

    def list_keys(self, prefix: str):
        return [key for key in self.objects if key.startswith(prefix)]


def test_after_local_write_pushes_to_backend(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    fake = _FakeBackend()
    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setattr(storage_backends, "_backend", fake)
    try:
        local = tmp_path / "demo" / "uploads" / "raw" / "a.pdf"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"%PDF-1.4 x")
        storage_backends.after_local_write(local)
        assert "projects/demo/uploads/raw/a.pdf" in fake.objects
    finally:
        settings.storage_root = previous
        storage_backends.reset_backend()


def test_ensure_local_hydrates_missing_file(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    fake = _FakeBackend()
    fake.objects["projects/demo/uploads/raw/a.pdf"] = b"%PDF-1.4 remote"
    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setattr(storage_backends, "_backend", fake)
    try:
        local = tmp_path / "demo" / "uploads" / "raw" / "a.pdf"
        assert not local.exists()
        storage_backends.ensure_local(local)
        assert local.read_bytes() == b"%PDF-1.4 remote"
    finally:
        settings.storage_root = previous
        storage_backends.reset_backend()


def test_local_backend_is_default(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    storage_backends.reset_backend()
    assert isinstance(storage_backends.get_backend(), storage_backends.LocalBackend)


def test_an_unknown_backend_name_is_refused(monkeypatch) -> None:
    """It used to fall back to local quietly, with the remote paths still on."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    storage_backends.reset_backend()
    with pytest.raises(RuntimeError, match="not one of"):
        storage_backends.get_backend()
    storage_backends.reset_backend()


def test_hydrate_project_pulls_what_the_disk_lacks(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    fake = _FakeBackend()
    fake.objects["projects/demo/uploads/raw/a.pdf"] = b"%PDF-1.4 remote a"
    fake.objects["projects/demo/extracted/openings.json"] = b"{}"
    fake.objects["projects/other/uploads/raw/c.pdf"] = b"%PDF-1.4 other"
    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setattr(storage_backends, "_backend", fake)
    try:
        kept = tmp_path / "demo" / "extracted" / "openings.json"
        kept.parent.mkdir(parents=True)
        kept.write_text('{"local": true}')

        root = storage_backends.hydrate_project("demo")

        assert root == tmp_path / "demo"
        assert (root / "uploads" / "raw" / "a.pdf").read_bytes() == b"%PDF-1.4 remote a"
        assert kept.read_text() == '{"local": true}'  # what is on disk wins
        assert not (tmp_path / "other").exists()
    finally:
        settings.storage_root = previous
        storage_backends.reset_backend()


FLOCI = (
    "DefaultEndpointsProtocol=https;AccountName=devstoreaccount1;"
    "AccountKey=ZmxvY2ktZGV2LW5vdC1hLXNlY3JldA==;"
    "BlobEndpoint=https://localhost:4577/devstoreaccount1;"
)


def test_the_azure_backend_round_trips_through_floci(tmp_path, monkeypatch) -> None:
    pytest.importorskip("azure.storage.blob")
    connection = os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or FLOCI
    endpoint = urlsplit(dict(p.split("=", 1) for p in connection.split(";") if "=" in p)["BlobEndpoint"])
    try:
        socket.create_connection((endpoint.hostname, endpoint.port or 443), timeout=1).close()
    except OSError:
        pytest.skip(f"no blob endpoint listening at {endpoint.netloc}")
    if endpoint.scheme == "https":
        # Floci's certificate is self-signed; fetching it is the one unverified
        # request, and everything after it is verified against that PEM.
        ca = tmp_path / "floci.pem"
        insecure = ssl._create_unverified_context()
        with urllib.request.urlopen(
            f"https://{endpoint.netloc}/_floci/tls-cert", context=insecure, timeout=5
        ) as response:
            ca.write_bytes(response.read())
        monkeypatch.setenv("AZURE_EMULATOR_CA", str(ca))
    container = f"cbc-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", connection)
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", container)
    backend = storage_backends.AzureBlobBackend()
    try:
        source = tmp_path / "a.pdf"
        source.write_bytes(b"%PDF-1.4 round trip")
        backend.put_file(source, "projects/demo/uploads/raw/a.pdf")
        backend.put_file(source, "projects/demo/uploads/raw/b.pdf")

        assert backend.exists("projects/demo/uploads/raw/a.pdf")
        assert sorted(backend.list_keys("projects/demo/")) == [
            "projects/demo/uploads/raw/a.pdf",
            "projects/demo/uploads/raw/b.pdf",
        ]
        back = tmp_path / "out" / "a.pdf"
        backend.get_file("projects/demo/uploads/raw/a.pdf", back)
        assert back.read_bytes() == source.read_bytes()
        assert not list(back.parent.glob(".*.part"))

        backend.delete("projects/demo/uploads/raw/a.pdf")
        backend.delete("projects/demo/uploads/raw/a.pdf")  # already gone: no error
        assert not backend.exists("projects/demo/uploads/raw/a.pdf")
        backend.delete_prefix("projects/demo/")
        assert list(backend.list_keys("projects/")) == []
    finally:
        backend._container.delete_container()
