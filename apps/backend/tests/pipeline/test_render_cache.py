"""Rendered-page cache: second call must not re-rasterise."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from cbc.core import pdfpages


def _tiny_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(path)
    finally:
        doc.close()
    return path


def test_second_page_image_does_not_rerender(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "pdf-pages"
    monkeypatch.setattr(pdfpages, "RENDER_CACHE", cache)
    pdf = _tiny_pdf(tmp_path / "sheet.pdf")

    calls = {"n": 0}
    real = fitz.Page.get_pixmap

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", counting)

    first = pdfpages.page_image(pdf, 1, dpi=72)
    second = pdfpages.page_image(pdf, 1, dpi=72)

    assert calls["n"] == 1
    assert Path(first["image_path"]) == Path(second["image_path"])
    rendered = Path(first["image_path"]).resolve()
    assert cache.resolve() in rendered.parents
    assert rendered.exists()


def test_render_cache_stays_out_of_uploads_raw(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdfpages, "ROOT", tmp_path)
    monkeypatch.setattr(pdfpages, "RENDER_CACHE", tmp_path / ".cache" / "pdf-pages")
    raw = tmp_path / "projects" / "demo" / "uploads" / "raw"
    raw.mkdir(parents=True)
    with pytest.raises(ValueError, match="uploads/raw"):
        pdfpages._writable_target(tmp_path / "sheet.pdf", raw)


def test_full_page_long_edge_is_clamped(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "pdf-pages"
    monkeypatch.setattr(pdfpages, "RENDER_CACHE", cache)
    doc = fitz.open()
    try:
        doc.new_page(width=2592, height=1728)
        pdf = tmp_path / "large.pdf"
        doc.save(pdf)
    finally:
        doc.close()

    result = pdfpages.page_image(pdf, 1, dpi=200)
    width, height = _png_size(Path(result["image_path"]))
    assert max(width, height) <= 1568
    assert result["dpi"] <= 200


def test_region_crop_is_smaller_and_does_not_share_the_full_page_cache(
    tmp_path, monkeypatch
) -> None:
    cache = tmp_path / "pdf-pages"
    monkeypatch.setattr(pdfpages, "RENDER_CACHE", cache)
    doc = fitz.open()
    try:
        doc.new_page(width=2592, height=1728)
        pdf = tmp_path / "large.pdf"
        doc.save(pdf)
    finally:
        doc.close()

    full = pdfpages.page_image(pdf, 1, dpi=200)
    cropped = pdfpages.page_image(pdf, 1, dpi=200, region=[0, 0, 144, 72])
    assert Path(full["image_path"]) != Path(cropped["image_path"])
    full_w, full_h = _png_size(Path(full["image_path"]))
    crop_w, crop_h = _png_size(Path(cropped["image_path"]))
    assert crop_w < full_w and crop_h < full_h
    assert crop_w == round(144 * cropped["dpi"] / 72)
    assert crop_h == round(72 * cropped["dpi"] / 72)


def _png_size(path: Path) -> tuple[int, int]:
    import struct

    with path.open("rb") as handle:
        signature = handle.read(8)
        assert signature == b"\x89PNG\r\n\x1a\n"
        handle.read(8)  # length + IHDR
        return struct.unpack(">II", handle.read(8))


def test_api_and_mcp_share_the_cache_name(tmp_path) -> None:
    pdf = _tiny_pdf(tmp_path / "sheet.pdf")
    name = pdfpages.render_cache_name(pdf, 1, 110)
    assert name.endswith(".png")
    assert len(Path(name).stem) == 24
    cropped = pdfpages.render_cache_name(pdf, 1, 110, region=[0, 0, 10, 10])
    assert cropped != name
