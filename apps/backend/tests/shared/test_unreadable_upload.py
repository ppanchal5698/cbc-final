"""An upload named .PDF is read, and one that will not open does not stop the bid."""
from __future__ import annotations

from cbc.modules.extraction.infrastructure import sheetmap
from cbc.shared.storage import pdfs_in


def test_pdfs_in_is_case_blind(tmp_path):
    for name in ("PLANS.PDF", "specs.pdf", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in pdfs_in(tmp_path)] == ["PLANS.PDF", "specs.pdf"]
    assert pdfs_in(tmp_path / "missing") == []


def test_a_corrupt_pdf_is_mapped_as_unreadable(tmp_path, monkeypatch):
    raw = tmp_path / "p1" / "uploads" / "raw"
    raw.mkdir(parents=True)
    (raw / "BROKEN.PDF").write_bytes(b"%PDF-1.4 garbage")
    monkeypatch.setattr(sheetmap, "storage_root", lambda: tmp_path)
    monkeypatch.setattr(sheetmap, "_project_relative", lambda slug, pdf: pdf.name)
    payload = sheetmap.build_sheetmap("p1", force=True)
    [entry] = payload["files"]
    assert entry["path"] == "BROKEN.PDF"
    assert entry["unreadable"] and entry["pages"] == []
