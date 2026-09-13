"""B-11: worker sheetmap pre-pass writes ranked pages and is a no-op on matching SHA."""
from __future__ import annotations

from pathlib import Path

import fitz

from cbc.worker_kit import prompts
from cbc.services import sheetmap


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
    monkeypatch.setattr(sheetmap, "PROJECTS", tmp_path / "projects")
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
    monkeypatch.setattr(sheetmap, "PROJECTS", tmp_path / "projects")
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


def test_roles_tag_frp_and_title_terms() -> None:
    pages = sheetmap._merge_pages(
        {
            "pages": [
                {"source_page": 1, "score": 5, "terms": {"architect": 2, "title block": 1}},
                {"source_page": 4, "score": 8, "terms": {"frp": 3, "wall panel": 1}},
            ]
        },
        [],
    )
    by_page = {p["source_page"]: p["roles"] for p in pages}
    assert "title" in by_page[1]
    assert "frp" in by_page[4]


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
    monkeypatch.setattr(sheetmap, "PROJECTS", tmp_path / "projects")
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
    assert "save_artifact" in text

