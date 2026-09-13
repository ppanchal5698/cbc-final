"""Malware scan and object-storage façade unit tests (no live ClamAV / AWS)."""
from __future__ import annotations

from pathlib import Path

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

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self.objects):
            if key.startswith(prefix):
                del self.objects[key]

    def exists(self, key: str) -> bool:
        return key in self.objects


def test_after_local_write_pushes_to_backend(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    fake = _FakeBackend()
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
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
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
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
