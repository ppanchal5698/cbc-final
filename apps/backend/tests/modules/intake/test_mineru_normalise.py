"""Normaliser covers pipeline / hybrid / VLM middle.json shapes and rotation."""
from __future__ import annotations

from pathlib import Path

import fitz

from cbc.modules.intake.api import mineru as mineru_api


def _sample_pipeline_page(w=612.0, h=792.0) -> dict:
    return {
        "page_size": [w, h],
        "para_blocks": [
            {
                "type": "text",
                "bbox": [72, 72, 300, 100],
                "lines": [
                    {
                        "bbox": [72, 72, 300, 100],
                        "spans": [{"content": "DOOR SCHEDULE"}],
                    }
                ],
            },
            {
                "type": "table",
                "bbox": [72, 120, 500, 400],
                "spans": [{"html": "<table><tr><td>101</td></tr></table>"}],
            },
        ],
        "discarded_blocks": [
            {
                "type": "text",
                "bbox": [500, 20, 580, 40],
                "lines": [{"spans": [{"content": "A2.1"}]}],
            }
        ],
    }


def _sample_hybrid_page() -> dict:
    """Hybrid nests list items under blocks."""
    return {
        "page_size": [612, 792],
        "para_blocks": [
            {
                "type": "list",
                "bbox": [72, 72, 400, 200],
                "blocks": [
                    {
                        "type": "text",
                        "bbox": [72, 72, 200, 90],
                        "lines": [{"spans": [{"content": "Item one"}]}],
                    },
                    {
                        "type": "text",
                        "bbox": [72, 100, 200, 118],
                        "lines": [{"spans": [{"content": "Item two"}]}],
                    },
                ],
            }
        ],
    }


def _sample_vlm_page() -> dict:
    return {
        "page_size": [612, 792],
        "para_blocks": [
            {
                "type": "code",
                "angle": 0,
                "bbox": [72, 200, 400, 280],
                "lines": [{"spans": [{"content": "HW-1"}]}],
            }
        ],
    }


def test_walk_blocks_pipeline_and_discarded():
    page = _sample_pipeline_page()
    blocks = mineru_api.walk_blocks(page["para_blocks"])
    blocks.extend(mineru_api.walk_blocks(page["discarded_blocks"], discarded=True))
    types = {b["type"] for b in blocks}
    assert "text" in types
    assert "table" in types
    assert "discarded" in types
    table = next(b for b in blocks if b["type"] == "table")
    assert "<table>" in (table.get("html") or "")


def test_walk_blocks_hybrid_nested_list():
    blocks = mineru_api.walk_blocks(_sample_hybrid_page()["para_blocks"])
    texts = [b["text"] for b in blocks]
    assert "Item one" in texts
    assert "Item two" in texts


def test_walk_blocks_vlm_code_angle():
    blocks = mineru_api.walk_blocks(_sample_vlm_page()["para_blocks"])
    assert blocks[0]["text"] == "HW-1"
    assert blocks[0].get("angle") == 0


def test_normalise_rotated_page(tmp_path: Path):
    """270° page: MinerU unrotated size is transposed vs page.rect; bboxes map."""
    pdf = tmp_path / "rot.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "TITLE BLOCK", fontsize=14)
    page.set_rotation(270)
    doc.save(pdf)
    doc.close()

    # After 270 rotation, display rect is 792 x 612.
    check = fitz.open(pdf)
    display = check[0].rect
    check.close()
    assert abs(display.width - 792) < 1
    assert abs(display.height - 612) < 1

    middle = {
        "pdf_info": [
            {
                # MinerU reports unrotated mediabox
                "page_size": [612, 792],
                "para_blocks": [
                    {
                        "type": "text",
                        "bbox": [72, 60, 200, 90],
                        "lines": [{"spans": [{"content": "TITLE BLOCK"}]}],
                    }
                ],
            }
        ]
    }
    rows = mineru_api.normalise_window(
        middle,
        pdf_path=pdf,
        start_page=1,
        project_id="p",
        document_id="d",
        content_sha="abc",
        parser={"name": "mineru", "backend": "pipeline"},
    )
    assert len(rows) == 1
    assert rows[0]["pageSize"]["width"] == round(display.width, 2)
    assert rows[0]["pageSize"]["height"] == round(display.height, 2)
    box = rows[0]["blocks"][0]["bbox"]
    # Mapped into display space — not identical to the unrotated claim.
    assert box != [72.0, 60.0, 200.0, 90.0]


def test_page_image_region_on_rotated_page(tmp_path: Path):
    """Crop region is display-space; page_image maps via inverse rotation_matrix."""
    from cbc.shared import pdfpages

    pdf = tmp_path / "rot2.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 200), "MARKER", fontsize=20)
    page.set_rotation(270)
    doc.save(pdf)
    doc.close()

    opened = fitz.open(pdf)
    page = opened[0]
    # Find the text in display space
    words = page.get_text("words")
    from cbc.shared.pdfrows import to_display_space

    words = to_display_space(page, words)
    opened.close()
    marker = next(w for w in words if "MARKER" in w[4])
    region = [marker[0] - 2, marker[1] - 2, marker[2] + 2, marker[3] + 2]

    out = pdfpages.page_image(pdf, 1, dpi=72, region=region)
    assert Path(out["image_path"]).exists()
    assert Path(out["image_path"]).stat().st_size > 0
