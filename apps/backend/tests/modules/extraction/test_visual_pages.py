"""Forced visual-read pre-render and validation gates."""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from cbc.modules.extraction.api.validation import artifacts, review
from cbc.modules.extraction.infrastructure import sheetmap, visual_pages


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


def _blank_scan_pdf(path: Path) -> Path:
    """Image-like page with no extractable text layer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        # Drawing only — no insert_text → empty get_text.
        page.draw_rect(page.rect, color=(0, 0, 0), width=1)
        doc.save(path)
    finally:
        doc.close()
    return path


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    monkeypatch.setattr(review, "ROOT", tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "projects"))
    return tmp_path


def test_build_visual_pages_renders_candidates(project_root, monkeypatch) -> None:
    slug = "vis_build"
    raw = project_root / "projects" / slug / "uploads" / "raw"
    pdf = _tiny_pdf(raw / "set.pdf", text="title")
    # Force sheetmap pages with needs_visual_read without relying on find_sheets.
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    path = f"projects/{slug}/uploads/raw/set.pdf"
    (extracted / "_sheetmap.json").write_text(
        json.dumps(
            {
                "generated_at": "t0",
                "files": [
                    {
                        "path": path,
                        "file_sha": "x",
                        "page_count": 1,
                        "schedule_pages": [],
                        "door_schedule_candidate_pages": [1],
                        "needs_visual_read_pages": [1],
                        "pages": [
                            {
                                "source_page": 1,
                                "roles": ["door_schedule_candidate", "text_poor"],
                                "char_count": 10,
                                "text_poor": True,
                                "has_text_layer": False,
                                "needs_visual_read": True,
                                "visual_reasons": ["no_text_layer", "text_poor", "door_schedule_candidate"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sheetmap, "build_sheetmap", lambda s, force=False: json.loads(
        (project_root / "projects" / s / "extracted" / "_sheetmap.json").read_text(encoding="utf-8")
    ))

    payload = visual_pages.build_visual_pages(slug, openings_seeded=0)
    assert payload["pages"]
    assert payload["pages"][0]["source_page"] == 1
    assert payload["pages"][0]["image_path"]
    assert Path(project_root / "projects" / slug / "extracted" / "_visual_pages.json").is_file()
    assert pdf.exists()


def test_empty_openings_without_visual_checklist_fails(project_root) -> None:
    slug = "vis_miss"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    path = f"projects/{slug}/uploads/raw/set.pdf"
    (extracted / "door_schedule.json").write_text(
        json.dumps({"openings": [], "no_scope_reason": "none"}),
        encoding="utf-8",
    )
    (extracted / "_sheetmap.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": path,
                        "door_schedule_candidate_pages": [16],
                        "needs_visual_read_pages": [16],
                        "pages": [
                            {
                                "source_page": 16,
                                "roles": ["door_schedule_candidate", "text_poor"],
                                "needs_visual_read": True,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (extracted / "_visual_pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "path": path,
                        "source_page": 16,
                        "reasons": ["text_poor", "door_schedule_candidate"],
                        "roles": ["door_schedule_candidate"],
                        "image_path": ".cache/pdf-pages/x.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction(slug)
    assert any("visual_pages_checked" in p for p in problems), problems
    assert any("missed read" in p or "candidate" in p.lower() for p in problems), problems


def test_visual_checklist_coverage_passes_with_openings(project_root) -> None:
    slug = "vis_ok"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    path = f"projects/{slug}/uploads/raw/set.pdf"
    (extracted / "door_schedule.json").write_text(
        json.dumps(
            {
                "openings": [
                    {
                        "door_number": "101",
                        "source_page": 16,
                        "bbox": [1, 2, 3, 4],
                        "page_size": {"width": 100, "height": 200},
                        "confidence": 0.9,
                    }
                ],
                "visual_pages_checked": [
                    {
                        "path": path,
                        "source_page": 16,
                        "image_path": ".cache/pdf-pages/x.png",
                        "finding": "schedule rows found",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (extracted / "_visual_pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "path": path,
                        "source_page": 16,
                        "reasons": ["door_schedule_candidate"],
                        "roles": ["door_schedule_candidate"],
                        "image_path": ".cache/pdf-pages/x.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction(slug)
    assert not any("visual_pages_checked" in p for p in problems), problems


def test_missing_visual_manifest_when_sheetmap_needs_it_fails(project_root) -> None:
    slug = "vis_prepare_bug"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text(
        json.dumps(
            {
                "openings": [
                    {
                        "door_number": "1",
                        "source_page": 1,
                        "bbox": [0, 0, 1, 1],
                        "page_size": {"width": 10, "height": 10},
                        "confidence": 0.8,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (extracted / "_sheetmap.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": f"projects/{slug}/uploads/raw/a.pdf",
                        "needs_visual_read_pages": [1],
                        "pages": [{"source_page": 1, "needs_visual_read": True}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction(slug)
    assert any("_visual_pages.json is missing" in p for p in problems), problems


def test_ocr_unavailable_review_flag(project_root) -> None:
    slug = "vis_ocr"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text(
        json.dumps({"openings": [], "no_scope_reason": "none"}),
        encoding="utf-8",
    )
    (extracted / "_visual_pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "path": f"projects/{slug}/uploads/raw/a.pdf",
                        "source_page": 2,
                        "ocr_status": "unavailable",
                        "reasons": ["no_text_layer"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    flags = review.derive_flags(slug)
    assert any(f.get("field") == "ocr_unavailable" for f in flags), flags


def test_visual_checklist_ignores_non_schedule_mineru_pages(project_root) -> None:
    """FRP / blank MinerU-null pages must not gate door_schedule coverage."""
    slug = "vis_frp_only"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    path = f"projects/{slug}/uploads/raw/set.pdf"
    (extracted / "door_schedule.json").write_text(
        json.dumps(
            {
                "openings": [
                    {
                        "door_number": "101",
                        "source_page": 14,
                        "bbox": [1, 2, 3, 4],
                        "page_size": {"width": 100, "height": 200},
                        "confidence": 0.9,
                    }
                ],
                "visual_pages_checked": [
                    {
                        "path": path,
                        "source_page": 28,
                        "image_path": ".cache/pdf-pages/x.png",
                        "finding": "schedule page checked",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (extracted / "_visual_pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "path": path,
                        "source_page": 16,
                        "reasons": ["mineru_verified_null"],
                        "roles": ["frp"],
                        "image_path": ".cache/pdf-pages/frp.png",
                    },
                    {
                        "path": path,
                        "source_page": 9,
                        "reasons": ["mineru_verified_null"],
                        "roles": [],
                        "image_path": ".cache/pdf-pages/blank.png",
                    },
                    {
                        "path": path,
                        "source_page": 28,
                        "reasons": ["mineru_verified_null"],
                        "roles": ["door_schedule"],
                        "image_path": ".cache/pdf-pages/x.png",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction(slug)
    assert not any("visual_pages_checked" in p for p in problems), problems
    assert artifacts._visual_manifest_schedule_pages(slug) == [(path, 28)]


def test_visual_checklist_ignores_frp_plus_hardware_pages(project_root) -> None:
    """Bare hardware co-tagged with FRP (Dutch Bros p20) must not gate door_schedule."""
    slug = "vis_frp_hw"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    path = f"projects/{slug}/uploads/raw/BUILDING PLANS.pdf"
    (extracted / "door_schedule.json").write_text(
        json.dumps(
            {
                "openings": [
                    {
                        "door_number": "01",
                        "source_page": 15,
                        "bbox": [1, 2, 3, 4],
                        "page_size": {"width": 100, "height": 200},
                        "confidence": 0.9,
                    }
                ],
                "visual_pages_checked": [
                    {
                        "path": path,
                        "source_page": 15,
                        "image_path": ".cache/pdf-pages/sched.png",
                        "finding": "door schedule rows",
                    },
                    {
                        "path": path,
                        "source_page": 25,
                        "image_path": ".cache/pdf-pages/cand.png",
                        "finding": "candidate — no extra openings",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (extracted / "_visual_pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "path": path,
                        "source_page": 15,
                        "reasons": ["mineru_verified_null"],
                        "roles": ["door_schedule", "hardware", "frp"],
                        "image_path": ".cache/pdf-pages/sched.png",
                    },
                    {
                        "path": path,
                        "source_page": 25,
                        "reasons": ["mineru_verified_null"],
                        "roles": ["door_schedule_candidate", "hardware"],
                        "image_path": ".cache/pdf-pages/cand.png",
                    },
                    {
                        "path": path,
                        "source_page": 20,
                        "reasons": ["mineru_verified_null"],
                        "roles": ["frp", "hardware"],
                        "image_path": ".cache/pdf-pages/frp_hw.png",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    problems, _ = artifacts.check_extraction(slug)
    assert not any("visual_pages_checked" in p for p in problems), problems
    assert artifacts._visual_manifest_schedule_pages(slug) == [
        (path, 15),
        (path, 25),
    ]
    checklist = visual_pages.prompt_checklist(slug)
    assert "page 15" in checklist
    assert "page 25" in checklist
    assert "page 20" not in checklist


def test_bbox_falls_back_to_row_bbox(project_root) -> None:
    slug = "bbox_row"
    extracted = project_root / "projects" / slug / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "door_schedule.json").write_text(
        json.dumps(
            {
                "openings": [
                    {
                        "door_number": "02",
                        "source_page": 14,
                        "bbox": None,
                        "row_bbox": [10.0, 20.0, 30.0, 40.0],
                        "page_size": {"width": 100, "height": 200},
                        "confidence": 0.8,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    problems, _ = artifacts.check_extraction(slug)
    assert not any("no valid bbox" in p for p in problems), problems
