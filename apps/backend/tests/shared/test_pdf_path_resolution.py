"""PDF paths from catalog tools must resolve outside repo cwd."""
from __future__ import annotations

from pathlib import Path

import pytest

from cbc.shared.pdfpages import resolve_pdf_path


def test_resolve_pricebook_path_from_repo_relative(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    books = root / "data" / "pricebooks"
    books.mkdir(parents=True)
    pdf = books / "hager_price_book_18.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    workspace = root / "scratch" / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    import cbc.shared.paths as paths

    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setattr(paths, "pricebook_dir", lambda: books)

    resolved = resolve_pdf_path("data/pricebooks/hager_price_book_18.pdf")
    assert resolved == pdf.resolve()


def test_resolve_pricebook_by_filename_only(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    books = root / "data" / "pricebooks"
    books.mkdir(parents=True)
    pdf = books / "vendor.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    import cbc.shared.paths as paths

    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setattr(paths, "pricebook_dir", lambda: books)

    assert resolve_pdf_path("vendor.pdf") == pdf.resolve()


def test_missing_pdf_raises(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    books = root / "data" / "pricebooks"
    books.mkdir(parents=True)

    import cbc.shared.paths as paths

    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setattr(paths, "pricebook_dir", lambda: books)

    with pytest.raises(FileNotFoundError, match="missing.pdf"):
        resolve_pdf_path("data/pricebooks/missing.pdf")
