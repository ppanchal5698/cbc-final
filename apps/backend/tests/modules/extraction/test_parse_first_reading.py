"""A page the parser read is answered from the parse, not from a picture of it.

The take-off used to be told, in the prompt and again by the validator, to read
the rendered PNG first and *not* to prefer the parsed blocks on schedule pages.
That was correct for MinerU, which could not be trusted on a CAD schedule. It
survived the swap to LlamaParse, which verifies those same sheets at 0.85-0.91
and carries per-cell boxes.

The measured cost on one 24-page bid: the take-off rendered two sheets
twenty-four times, spent 48 of its 80 tool calls on `get_page_image` -> `Read`
pairs, hit its 80-turn cap, and produced one patch - while the door schedule sat
parsed in Mongo one `get_page_blocks` call away. Hitting the cap means the
verification was truncated, so this was costing accuracy, not buying it.

These pin the rule that replaced it: the parser's own `verified` score decides
whether a page needs eyes.
"""
from __future__ import annotations

import json

import pytest

from cbc.modules.extraction.infrastructure import visual_pages


def _page(**over):
    page = {
        "path": "uploads/raw/set.pdf",
        "source_page": 16,
        "roles": ["door_schedule"],
        "reasons": [],
        "verified": 0.85,
        "image_path": "extracted/_visual_pages/abc.png",
    }
    page.update(over)
    return page


def test_a_verified_schedule_page_needs_no_image() -> None:
    """0.849 and 0.913 are what LlamaParse returned on the first real bid."""
    assert visual_pages.parse_can_answer(_page(verified=0.849)) is True
    assert visual_pages.parse_can_answer(_page(verified=0.913)) is True


def test_a_page_with_no_text_layer_still_needs_eyes() -> None:
    """`verified: null` means the parser had nothing to compare against."""
    assert visual_pages.parse_can_answer(
        _page(verified=None, reasons=["parser_verified_null"])
    ) is False


def test_a_text_poor_page_still_needs_eyes() -> None:
    assert visual_pages.parse_can_answer(
        _page(verified=0.9, reasons=["text_poor"])
    ) is False


def test_a_weakly_verified_page_still_needs_eyes() -> None:
    """Below the floor the parse is not worth trusting over a look."""
    assert visual_pages.parse_can_answer(_page(verified=0.3)) is False


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    def write(pages):
        root = tmp_path / "bid" / "extracted"
        root.mkdir(parents=True, exist_ok=True)
        (root / "_visual_pages.json").write_text(
            json.dumps({"pages": pages}), encoding="utf-8"
        )
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
        from cbc.shared.config import settings

        monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
        return "bid"

    return write


def test_only_unreadable_pages_reach_the_checklist(manifest) -> None:
    slug = manifest([
        _page(source_page=16, verified=0.849),
        _page(source_page=7, verified=0.913),
        _page(source_page=1, verified=None, reasons=["parser_verified_null"]),
    ])

    needing = [p["source_page"] for p in visual_pages.pages_needing_vision(slug)]

    assert needing == [1], "a verified schedule page was still forced to a render"

    block = visual_pages.prompt_checklist(slug)
    assert "Read the parse before you render anything" in block
    assert "page 1" in block
    # The two sheets the old prompt sent it hunting across.
    assert "page 16" not in block
    assert "page 7" not in block


def test_handing_stays_a_vision_read(manifest) -> None:
    """It is read off the door swing and printed as text nowhere."""
    slug = manifest([_page(verified=0.9)])
    assert "handing" in visual_pages.prompt_checklist(slug)


def test_a_fully_parsed_bid_says_so(manifest) -> None:
    slug = manifest([_page(source_page=16, verified=0.9)])
    block = visual_pages.prompt_checklist(slug)
    assert "No schedule page on this bid needs a vision read" in block


def test_the_validator_only_requires_what_the_parser_could_not_read(manifest) -> None:
    """The prompt and the validator must agree, or the run fails either way.

    This is the pairing that kept the loop alive: the checklist could stop asking
    for pictures, but `check_extraction` still failed a run that did not report
    one for every schedule page.
    """
    from cbc.modules.extraction.api.validation import artifacts

    slug = manifest([
        _page(source_page=16, verified=0.849),
        _page(source_page=1, verified=None, reasons=["parser_verified_null"]),
    ])

    required = artifacts._visual_manifest_schedule_pages(slug)

    assert [page for _, page in required] == [1]


def test_the_checklist_hands_over_the_rectangle_it_already_measured(manifest, tmp_path):
    """A crop the seed measured is pasted, not hunted for.

    The checklist told the model to crop the seeded rectangle without ever saying
    what it was. On the re-run that still cost six crops of a floor plan and five
    of a schedule sheet whose rows were boxed in the artifact beside it.
    """
    slug = manifest([_page(verified=0.9)])
    extracted = tmp_path / slug / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "line_items.json").write_text(
        json.dumps(
            {
                "openings": [
                    {"door_number": "02", "source_page": 16, "bbox": [80, 227, 668, 235]},
                    {"door_number": "07", "source_page": 16, "bbox": None},
                ]
            }
        ),
        encoding="utf-8",
    )

    regions = visual_pages.seeded_row_regions(slug)

    assert list(regions) == [16], "only pages with a measured row"
    marks = [mark for mark, _ in regions[16]]
    assert marks[0] == "02" and "07" not in marks, "a null bbox is not a rectangle"

    # A row box is ~8pt tall; cropped exactly it renders a sliver.
    x0, y0, x1, y1 = regions[16][0][1]
    assert y1 - y0 > 60, "no vertical context around the row"
    assert x0 < 80 and x1 > 600, "the row's own width is not covered"

    assert f"region={regions[16][0][1]}" in visual_pages.prompt_checklist(slug)


def test_a_row_too_wide_to_read_is_banded(manifest, tmp_path):
    """Resolution follows width: 1900pt renders at 0.84 px/pt and is unreadable.

    Three of six Wendys rows span nearly the full sheet, because a note in the
    right margin shares their y-band. Handing one over whole is handing over a
    crop the model must immediately re-crop - the loop this is meant to end.
    """
    slug = manifest([_page(verified=0.9)])
    extracted = tmp_path / slug / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "line_items.json").write_text(
        json.dumps(
            {"openings": [{"door_number": "03", "source_page": 16, "bbox": [80, 227, 1920, 235]}]}
        ),
        encoding="utf-8",
    )

    bands = visual_pages.seeded_row_regions(slug)[16]

    assert len(bands) == 2, "a 1840pt row was handed over in one unreadable strip"
    assert all(
        region[2] - region[0] <= visual_pages.CROP_MAX_WIDTH for _mark, region in bands
    )
    assert bands[1][0].endswith("(cont.)")
    assert bands[1][1][0] == bands[0][1][2], "the bands must not leave a gap"


def _plan_pdf(tmp_path, marks_at, size=(1000, 1000)):
    """A floor plan with each mark printed as its own tag at a given spot."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=size[0], height=size[1])
    for mark, (x, y) in marks_at.items():
        page.insert_text((x, y), mark, fontsize=9)
    path = tmp_path / "plan.pdf"
    doc.save(path)
    doc.close()
    return path


def _handing_project(tmp_path, monkeypatch, marks_at, openings, size=(1000, 1000)):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from cbc.shared.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    slug = "bid"
    extracted = tmp_path / slug / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    raw = tmp_path / slug / "uploads" / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    plan = _plan_pdf(tmp_path, marks_at, size)
    (raw / "plan.pdf").write_bytes(plan.read_bytes())
    (extracted / "_sheetmap.json").write_text(
        json.dumps(
            {"files": [{"path": f"projects/{slug}/uploads/raw/plan.pdf",
                        "pages": [{"source_page": 1, "roles": ["floor_plan"]}]}]}
        ),
        encoding="utf-8",
    )
    (extracted / "line_items.json").write_text(
        json.dumps({"openings": openings}), encoding="utf-8"
    )
    return slug


def test_one_crop_answers_every_door_whose_marks_sit_together(tmp_path, monkeypatch):
    """Handing is the one field that is genuinely a picture, and it was hunted for.

    On a real 24-page bid the take-off rendered the same floor plan six times
    looking for doors whose tags are printed in the text layer. Four of them sit
    inside one 300pt square.
    """
    slug = _handing_project(
        tmp_path, monkeypatch,
        {"05": (500, 500), "06": (520, 520), "08": (540, 540)},
        [{"door_number": m, "handing": None} for m in ("05", "06", "08")],
    )

    regions = visual_pages.handing_regions(slug)

    assert len(regions) == 1, f"one cluster, one picture - got {regions}"
    assert regions[0]["marks"] == ["05", "06", "08"]
    assert regions[0]["page"] == 1


def test_a_door_on_its_own_gets_its_own_crop(tmp_path, monkeypatch):
    slug = _handing_project(
        tmp_path, monkeypatch,
        {"05": (100, 100), "09": (900, 900)},
        [{"door_number": m, "handing": None} for m in ("05", "09")],
    )

    regions = visual_pages.handing_regions(slug)

    assert sorted(m for r in regions for m in r["marks"]) == ["05", "09"]
    assert len(regions) == 2


def test_a_crop_never_runs_off_the_sheet(tmp_path, monkeypatch):
    """A negative corner renders somewhere else entirely."""
    slug = _handing_project(
        tmp_path, monkeypatch, {"05": (5, 5)}, [{"door_number": "05", "handing": None}]
    )

    x0, y0, x1, y1 = visual_pages.handing_regions(slug)[0]["region"]

    assert x0 >= 0 and y0 >= 0
    assert x1 <= 1000 and y1 <= 1000
    assert x1 - x0 == visual_pages.HANDING_CROP, "clamping must not shrink it illegible"


def test_a_door_that_already_has_handing_is_not_cropped_for(tmp_path, monkeypatch):
    slug = _handing_project(
        tmp_path, monkeypatch,
        {"05": (500, 500), "06": (900, 100)},
        [{"door_number": "05", "handing": "LH"}, {"door_number": "06", "handing": None}],
    )

    regions = visual_pages.handing_regions(slug)

    assert [m for r in regions for m in r["marks"]] == ["06"]


def test_an_out_of_scope_door_is_not_cropped_for(tmp_path, monkeypatch):
    """Storefront is not CBC's to hand."""
    slug = _handing_project(
        tmp_path, monkeypatch,
        {"02": (500, 500)},
        [{"door_number": "02", "handing": None, "in_scope": False}],
    )

    assert visual_pages.handing_regions(slug) == []


def test_a_mark_inside_a_dimension_is_not_a_door(tmp_path, monkeypatch):
    """Matching loosely sends the estimator to a dimension line, confidently."""
    slug = _handing_project(
        tmp_path, monkeypatch,
        {"5'-0\"": (500, 500)},
        [{"door_number": "05", "handing": None}],
    )

    assert visual_pages.handing_regions(slug) == []
