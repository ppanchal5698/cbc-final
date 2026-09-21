"""B-11: worker sheetmap pre-pass writes ranked pages and is a no-op on matching SHA."""
from __future__ import annotations

import json
from pathlib import Path

import fitz

from cbc.worker_kit import prompts
from cbc.modules.extraction.infrastructure import sheetmap


def _tiny_pdf(path: Path, text: str = "DOOR SCHEDULE") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 80), text, fontsize=12)
        doc.save(path)
    finally:
        doc.close()
    return path


def test_the_path_is_the_one_a_tool_takes(tmp_path, monkeypatch) -> None:
    """It was `uploads/raw/<name>`, so every caller retyped the project slug in
    front of it. One run typed `dunkin_donots_remodel` and the three searches
    hunting for the door schedule came back "PDF not found"."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = "sheetmap_paths"
    _tiny_pdf(tmp_path / "projects" / slug / "uploads" / "raw" / "set.pdf")

    entry = sheetmap.build_sheetmap(slug)["files"][0]

    assert entry["path"] == f"projects/{slug}/uploads/raw/set.pdf"
    # And the SHA short-circuit still recognises its own output: _unchanged
    # rebuilds this key, so a mismatch there would re-run find_sheets every job.
    again = sheetmap.build_sheetmap(slug)
    assert again["generated_at"] == sheetmap.build_sheetmap(slug)["generated_at"]
    assert again["files"][0]["path"] == entry["path"]


def test_schedule_markers_are_stated_not_inferred(tmp_path, monkeypatch) -> None:
    """An accessibility sheet scored 44 on the word "door" alone and led the map
    on a bid whose Division 08 scope was nil. A run needs to be able to read
    "no page here carries a schedule marker" as a fact."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = "sheetmap_markers"
    _tiny_pdf(
        tmp_path / "projects" / slug / "uploads" / "raw" / "ada.pdf",
        text="ACCESSIBLE DOORS REQUIREMENTS door hardware door closer",
    )

    entry = sheetmap.build_sheetmap(slug)["files"][0]

    assert entry["has_schedule_markers"] is False
    assert entry["schedule_pages"] == []


def test_a_schedule_page_outranks_a_higher_scoring_word_count() -> None:
    ranked = {
        "pages": [
            {"source_page": 2, "score": 44, "terms": {"door": 30}},
            {"source_page": 9, "score": 3, "terms": {"door": 2}},
        ]
    }
    markers = [{"source_page": 9, "markers": ["DOOR SCHEDULE"]}]

    pages = sheetmap._merge_pages(ranked, markers)

    assert pages[0]["source_page"] == 9, "the real schedule must lead the map"
    assert pages[0]["kind"] == "schedule"
    assert "door_schedule" in pages[0]["roles"]


def test_text_poor_a4_sheet_gets_door_schedule_candidate() -> None:
    """CAD schedule sheets often have title-block-only text; still flag for image review."""
    ranked = {
        "pages": [
            {
                "source_page": 37,
                "score": 19,
                "terms": {"door": 6, "partition": 6},
                "sheet_ids": ["E3.0"],
                "char_count": 40000,
            },
            {
                "source_page": 16,
                "score": 0,
                "terms": {},
                "sheet_ids": ["A4.0"],
                "char_count": 166,
            },
            {
                "source_page": 17,
                "score": 0,
                "terms": {"storefront": 3, "window type": 2},
                "sheet_ids": ["A4.1"],
                "char_count": 166,
            },
            {
                "source_page": 18,
                "score": 0,
                "terms": {},
                "sheet_ids": ["A2.2"],
                "char_count": 200,
            },
            {
                "source_page": 6,
                "score": 2,
                "terms": {"floor plan": 1},
                "sheet_ids": ["A1.0"],
                "char_count": 249,
            },
        ]
    }

    pages = sheetmap._merge_pages(ranked, [])
    by_page = {p["source_page"]: p for p in pages}

    assert "door_schedule_candidate" in by_page[16]["roles"]
    assert "text_poor" in by_page[16]["roles"]
    assert "hardware" in by_page[16]["roles"]
    assert by_page[16]["text_poor"] is True
    assert by_page[16]["needs_visual_read"] is True
    assert by_page[16]["has_text_layer"] is True  # 166 >= 40
    assert "text_poor" in by_page[16]["visual_reasons"]
    # A4.1 with storefront/window cues — soft-excluded from schedule candidates.
    assert "door_schedule_candidate" not in by_page[17]["roles"]
    # A2.2 text-poor is a common schedule sheet (not only A4.0).
    assert "door_schedule_candidate" in by_page[18]["roles"]
    assert "floor_plan" in by_page[6]["roles"]
    # Candidate outranks pure word-count noise on electrical specs.
    assert pages[0]["source_page"] in (16, 18)


def test_no_text_layer_forces_visual_read() -> None:
    pages = sheetmap._merge_pages(
        {
            "pages": [
                {
                    "source_page": 3,
                    "score": 0,
                    "terms": {},
                    "sheet_ids": [],
                    "char_count": 5,
                }
            ]
        },
        [],
    )
    assert pages[0]["has_text_layer"] is False
    assert pages[0]["needs_visual_read"] is True
    assert "no_text_layer" in pages[0]["visual_reasons"]


def test_text_rich_page_without_schedule_role_not_forced() -> None:
    pages = sheetmap._merge_pages(
        {
            "pages": [
                {
                    "source_page": 2,
                    "score": 1,
                    "terms": {"elevation": 2},
                    "sheet_ids": ["A2.1"],
                    "char_count": 12000,
                }
            ]
        },
        [],
    )
    assert pages[0]["has_text_layer"] is True
    assert pages[0]["text_poor"] is False
    assert pages[0]["needs_visual_read"] is False
    assert pages[0]["visual_reasons"] == []


def test_mineru_empty_blocks_force_visual_read() -> None:
    page = {
        "source_page": 9,
        "roles": ["door_schedule"],
        "char_count": 8000,
        "text_poor": False,
    }
    needs, reasons = sheetmap.page_needs_visual_read(
        page, mineru={"verified": None, "block_count": 0}
    )
    assert needs is True
    assert "mineru_verified_null" in reasons
    assert "mineru_empty_blocks" in reasons


def test_select_visual_targets_caps_and_prioritises() -> None:
    sheet = {
        "files": [
            {
                "path": "projects/x/uploads/raw/a.pdf",
                "pages": [
                    {
                        "source_page": 1,
                        "needs_visual_read": True,
                        "visual_reasons": ["text_poor"],
                        "roles": ["text_poor"],
                    },
                    {
                        "source_page": 16,
                        "needs_visual_read": True,
                        "visual_reasons": ["door_schedule_candidate", "text_poor"],
                        "roles": ["door_schedule_candidate", "text_poor"],
                    },
                ],
            }
        ]
    }
    targets = sheetmap.select_visual_targets(sheet, cap=1)
    assert len(targets) == 1
    assert targets[0]["source_page"] == 16


def test_roles_tag_frp_and_title_terms() -> None:
    pages = sheetmap._merge_pages(
        {
            "pages": [
                {"source_page": 1, "score": 5, "terms": {"architect": 2, "title block": 1}},
                {"source_page": 4, "score": 8, "terms": {"frp": 3, "wall panel": 1}},
                {"source_page": 6, "score": 4, "terms": {"floor plan": 2}},
                {"source_page": 8, "score": 3, "terms": {"toilet partition": 1, "hand dryer": 1}},
                {"source_page": 10, "score": 2, "terms": {"division 08": 1, "hollow metal": 1}},
            ]
        },
        [],
    )
    by_page = {p["source_page"]: p["roles"] for p in pages}
    assert "title" in by_page[1]
    assert "frp" in by_page[4]
    assert "floor_plan" in by_page[6]
    assert "div10" in by_page[8]
    assert "div08_specs" in by_page[10]


def test_pages_for_roles_filters() -> None:
    hits = sheetmap.pages_for_roles(
        {
            "files": [
                {
                    "path": "projects/x/uploads/raw/a.pdf",
                    "pages": [
                        {"source_page": 1, "roles": ["title"], "kind": "ranked"},
                        {"source_page": 9, "roles": ["door_schedule"], "kind": "schedule"},
                    ],
                }
            ]
        },
        "door_schedule",
    )
    assert len(hits) == 1
    assert hits[0]["source_page"] == 9


def test_build_sheetmap_ranks_pages_and_skips_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = "sheetmap_demo"
    pdf = _tiny_pdf(tmp_path / "projects" / slug / "uploads" / "raw" / "set.pdf")
    first = sheetmap.build_sheetmap(slug)
    target = sheetmap.sheetmap_path(slug)
    assert target.is_file()
    assert first["files"]
    pages = first["files"][0]["pages"]
    assert pages
    assert any(p.get("markers") or "door" in str(p.get("terms")).lower() for p in pages)
    generated = first["generated_at"]
    second = sheetmap.build_sheetmap(slug)
    assert second["generated_at"] == generated
    assert pdf.exists()
    forced = sheetmap.build_sheetmap(slug, force=True)
    assert forced["generated_at"] != generated


def test_extract_prompt_names_the_sheetmap() -> None:
    text = prompts.build(
        {"type": "extract_bid_set", "payload": {}},
        {"slug": "demo", "code": "CBC-1"},
    )
    assert "_sheetmap.json" in text
    assert "find_sheets" in text
    assert "roles" in text
    assert "frp_in_scope" in text
    assert "div10_in_scope" in text
    assert "div10-specialist" in text
    assert "div08_specs" in text
    assert "floor_plan" in text
    assert "save_artifact" in text
    assert "_visual_pages.json" in text


def test_extract_prompt_includes_visual_checklist(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    slug = "vis_prompt"
    extracted = tmp_path / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "_visual_pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "path": f"projects/{slug}/uploads/raw/set.pdf",
                        "source_page": 16,
                        "reasons": ["text_poor", "door_schedule_candidate"],
                        "image_path": ".cache/pdf-pages/demo.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    text = prompts.build(
        {"type": "extract_bid_set", "payload": {}},
        {"slug": slug, "code": "CBC-VIS"},
    )
    assert "Mandatory visual reads" in text
    assert "page 16" in text
    assert "visual_pages_checked" in text



def test_an_edited_parser_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    """`.claude` is a bind mount and the worker is long-lived.

    The loader cached on the module name alone, so an edit to
    `parse_schedule.py` landed on disk under a process that had already
    imported it and was served the pre-edit module for the life of the worker.
    Observed exactly that: a fix to the schedule row parser was applied, a bid
    re-run, and the rows came back byte-identical with nothing in any log to
    say why.
    """
    import sys

    from cbc.modules.extraction.infrastructure import sheetmap

    skill = tmp_path / ".claude" / "skills" / "extract-door-schedule" / "scripts"
    skill.mkdir(parents=True)
    target = skill / "parse_schedule.py"
    target.write_text("VERSION = 'before'\n", encoding="utf-8")
    monkeypatch.setattr(sheetmap, "ROOT", tmp_path)
    sys.modules.pop("cbc_parse_schedule", None)
    try:
        assert sheetmap._load_parse_schedule().VERSION == "before"

        # Same path, new contents - what editing the skill actually looks like.
        target.write_text("VERSION = 'after'\n", encoding="utf-8")
        import os

        stamp = target.stat().st_mtime_ns + 1_000_000
        os.utime(target, ns=(stamp, stamp))

        assert sheetmap._load_parse_schedule().VERSION == "after", (
            "the loader served a stale module after the file changed"
        )
    finally:
        sys.modules.pop("cbc_parse_schedule", None)


def test_an_unchanged_parser_is_not_re_imported(tmp_path, monkeypatch):
    """Re-importing on every call would cost a file read per sheet-map build."""
    import sys

    from cbc.modules.extraction.infrastructure import sheetmap

    skill = tmp_path / ".claude" / "skills" / "extract-door-schedule" / "scripts"
    skill.mkdir(parents=True)
    (skill / "parse_schedule.py").write_text("VERSION = 'x'\n", encoding="utf-8")
    monkeypatch.setattr(sheetmap, "ROOT", tmp_path)
    sys.modules.pop("cbc_parse_schedule", None)
    try:
        first = sheetmap._load_parse_schedule()
        assert sheetmap._load_parse_schedule() is first
    finally:
        sys.modules.pop("cbc_parse_schedule", None)
