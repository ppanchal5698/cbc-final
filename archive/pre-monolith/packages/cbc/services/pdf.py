"""PDF services for the review screen.

The estimator checks an extracted value against the real drawing, so the API
serves real page renders and the raw file. Bboxes come from extraction and are
measured in PDF points against `page_size`; the viewer scales them itself.

The page operations come from `cbc_core.pdfpages`, which the pdf-tools MCP server
also uses - so a bbox the estimator is shown is measured against exactly the frame
a run recorded it in. This module adds the render cache on top.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cbc.core import pdfpages

RENDER_CACHE = pdfpages.RENDER_CACHE  # one cache, shared with the MCP server
MAX_DPI = 300
MIN_DPI = 36

page_count = pdfpages.page_count
find_text = pdfpages.find_text


def page_size(path: Path, page_number: int) -> dict[str, Any]:
    return pdfpages.page_size(path, page_number)


def render_page(path: Path, page_number: int, dpi: int = 110) -> Path:
    """Render one page to PNG, cached by file content + page + dpi.

    The filename is the content SHA-256 of the PDF (plus page, dpi, region,
    renderer), computed in pdfpages so the API and the MCP server share one
    file. Long-edge clamping also lives there, so this wrapper must not invent
    a second cache key.
    """
    dpi = max(MIN_DPI, min(int(dpi), MAX_DPI))
    RENDER_CACHE.mkdir(parents=True, exist_ok=True)
    return Path(
        pdfpages.page_image(path, page_number=page_number, dpi=dpi, out_dir=RENDER_CACHE)[
            "image_path"
        ]
    )
