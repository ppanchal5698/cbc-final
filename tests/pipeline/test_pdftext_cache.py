"""C-02 / B-12: PDF text and table extraction must not re-scan an unchanged file."""
from __future__ import annotations

from pathlib import Path

import fitz

from cbc.core import pdfrows, pdftext

from _runtime import load_server


def _tiny_pdf(path: Path, text: str = "DOOR SCHEDULE") -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 80), text, fontsize=12)
        doc.save(path)
    finally:
        doc.close()
    return path


def _pdf_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(pdftext, "CACHE_DB", tmp_path / "pdftext.db")
    pdftext.reset()
    return load_server("pdf-tools")


def test_second_find_sheets_does_not_rescan(tmp_path, monkeypatch) -> None:
    pdf = _pdf_tools(tmp_path, monkeypatch)
    sheet = _tiny_pdf(tmp_path / "sheet.pdf")
    calls = {"n": 0}
    real = fitz.Page.get_text

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_text", counting)
    first = pdf.find_sheets(str(sheet))
    after_first = calls["n"]
    second = pdf.find_sheets(str(sheet))
    assert calls["n"] == after_first
    assert first["pages"] == second["pages"]
    assert first["pages"]


def test_second_extract_tables_does_not_recluster(tmp_path, monkeypatch) -> None:
    pdf = _pdf_tools(tmp_path, monkeypatch)
    sheet = _tiny_pdf(tmp_path / "sheet.pdf")
    calls = {"n": 0}
    real = pdfrows.rows_from_words

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(pdfrows, "rows_from_words", counting)
    first = pdf.extract_tables(str(sheet), page_range="1")
    after_first = calls["n"]
    second = pdf.extract_tables(str(sheet), page_range="1")
    assert calls["n"] == after_first
    assert first["pages"] == second["pages"]


def test_second_search_pdf_uses_cached_text(tmp_path, monkeypatch) -> None:
    pdf = _pdf_tools(tmp_path, monkeypatch)
    sheet = _tiny_pdf(tmp_path / "sheet.pdf")
    calls = {"n": 0}
    real = fitz.Page.get_text

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_text", counting)
    pdf.search_pdf(str(sheet), "DOOR")
    after_first = calls["n"]
    again = pdf.search_pdf(str(sheet), "DOOR")
    assert calls["n"] == after_first
    assert again["hit_count"] >= 1


def test_pdftext_opens_in_wal_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdftext, "CACHE_DB", tmp_path / "pdftext.db")
    pdftext.reset()
    mode = pdftext._connect().execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


def test_extractor_version_bump_misses_the_cache(tmp_path, monkeypatch) -> None:
    pdf = _pdf_tools(tmp_path, monkeypatch)
    sheet = _tiny_pdf(tmp_path / "sheet.pdf")
    pdf.find_sheets(str(sheet))
    calls = {"n": 0}
    real = fitz.Page.get_text

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_text", counting)
    monkeypatch.setattr(pdfrows, "EXTRACTOR_VERSION", pdfrows.EXTRACTOR_VERSION + "-next")
    pdf.find_sheets(str(sheet))
    assert calls["n"] > 0
