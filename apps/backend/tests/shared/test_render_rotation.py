"""A region crop must show the region asked for, on a rotated page too.

72 of the 87 sheets in one real bid set are rotated 270. `page_image` used to
un-rotate the clip before handing it to `get_pixmap`, which already renders the
page as displayed — so the rotation was applied twice. The crop came back
transposed when it worked at all, and collapsed to a zero-height pixmap when it
did not, surfacing as MuPDF's "code=4: Invalid bandwriter header
dimensions/setup".

An agent cropping to read a schedule row got a picture of somewhere else, with
nothing to tell it so. One run spent sixteen minutes and about twenty crops on
a rotated sheet and produced no output at all.
"""
from __future__ import annotations

import pytest

from cbc.shared import pdfpages


class _Rect:
    def __init__(self, w: float, h: float) -> None:
        self.width, self.height = w, h


class _Page:
    def __init__(self, w_in: float, h_in: float) -> None:
        self.rect = _Rect(w_in * 72, h_in * 72)


def test_a_wide_region_is_reported_as_unreadable_not_silently_returned():
    """The cap is on pixels, so more dpi cannot help — only a smaller region.

    Asking for 300 dpi over most of a sheet used to return a 0.9 px/pt image
    and call it a success.
    """
    sheet = _Page(34, 22)
    wide = [0, 0, 1786, 900]
    dpi = pdfpages._clamp_dpi(300, sheet, wide)

    px_per_pt = pdfpages.MAX_LONG_EDGE_PX / max(wide[2] - wide[0], wide[3] - wide[1])
    assert px_per_pt < pdfpages.LEGIBLE_PX_PER_PT, "this region must read as illegible"
    assert dpi < 100, "and the dpi it gets should make that obvious"


def test_a_tight_crop_clears_the_legibility_floor():
    sheet = _Page(34, 22)
    tight = [1150, 600, 1500, 800]
    px_per_pt = pdfpages.MAX_LONG_EDGE_PX / max(tight[2] - tight[0], tight[3] - tight[1])

    assert px_per_pt >= pdfpages.LEGIBLE_PX_PER_PT
    assert pdfpages._clamp_dpi(300, sheet, tight) == 300


def test_the_clip_is_not_un_rotated(tmp_path):
    """The source-level guard: `page_image` must hand `get_pixmap` the region as
    given. Re-introducing `clip * ~page.rotation_matrix` is the bug."""
    import inspect

    body = inspect.getsource(pdfpages.page_image)
    assert "rotation_matrix" not in body, (
        "the clip must stay in display space - get_pixmap already honours rotation"
    )
    assert "clip=clip" in body
