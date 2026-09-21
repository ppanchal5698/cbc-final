"""A rendered page is priced by pixel area, so the render is where cost is set.

Vision input costs roughly (width x height) / 750 tokens, and a rendered page
then sits in the conversation for the rest of the pass — rewritten in full on
every cold prefix write. `_clamp_dpi` is the only thing standing between a
request for 300 dpi and a five-figure token bill in one tool result.
"""
from __future__ import annotations

from cbc.shared import pdfpages


class _Rect:
    def __init__(self, width: float, height: float) -> None:
        self.width, self.height = width, height


class _Page:
    """Just the `.rect` that `_clamp_dpi` reads, so this needs no PDF."""

    def __init__(self, width_in: float, height_in: float) -> None:
        self.rect = _Rect(width_in * 72, height_in * 72)


E_SIZE = _Page(42, 30)  # a normal architectural sheet


def _tokens(dpi: int, width_pt: float, height_pt: float) -> int:
    return round(width_pt / 72 * dpi) * round(height_pt / 72 * dpi) // 750


def test_a_big_region_can_no_longer_skip_the_clamp():
    """`if region: return dpi` let a crop render at the full 300 dpi.

    Fine for the row-sized crops it was meant for; ruinous for half a sheet,
    which came to about 37,800 vision tokens in a single tool result. Nothing
    passed a large region automatically, so this was latent - but it goes live
    the moment anything pre-renders crops instead of full pages.
    """
    half_sheet = [0, 0, 21 * 72, 15 * 72]
    dpi = pdfpages._clamp_dpi(300, E_SIZE, half_sheet)

    assert _tokens(dpi, 21 * 72, 15 * 72) < 4_000, (
        f"half a sheet at {dpi} dpi is {_tokens(dpi, 21*72, 15*72)} tokens"
    )
    assert round(21 * 72 / 72 * dpi) <= pdfpages.MAX_LONG_EDGE_PX


def test_a_row_sized_crop_stays_exactly_as_sharp():
    """The clamp must bound the big case without softening the useful one.

    A 200pt band allows ~564 dpi before it reaches the long-edge cap, so the
    300 dpi ceiling still governs and the crop is unchanged.
    """
    row_band = [0, 0, 200, 140]
    assert pdfpages._clamp_dpi(300, E_SIZE, row_band) == 300, (
        "a crop small enough to fit the pixel cap must get the dpi it asked for"
    )


def test_a_full_sheet_is_still_clamped_to_the_long_edge():
    dpi = pdfpages._clamp_dpi(200, E_SIZE, None)
    assert round(42 * 72 / 72 * dpi) <= pdfpages.MAX_LONG_EDGE_PX
    assert dpi >= pdfpages.MIN_DPI
