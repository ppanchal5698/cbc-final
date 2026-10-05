"""The bid digest: every page in reading order, each block anchored and trusted only when the sheet agrees."""
from __future__ import annotations

from cbc.modules.intake.api import digest
from cbc.modules.ops.api import page_blocks, parsing_config


def test_a_block_the_sheet_agrees_with_is_plain_and_one_it_does_not_is_marked():
    doc = {"_id": "d1", "filename": "A6.0 Door Schedule.pdf"}
    pages = [{
        "page": 12,
        "parser": {"name": "nemotron-parse"},
        "blocks": [
            {"n": 1, "type": "section-header", "text": "## HARDWARE SET NO. 3", "bbox": [10, 10, 200, 30], "agrees": 1.0},
            {"n": 2, "type": "text", "text": "3 EA HINGE BB1279 US26D", "bbox": [10, 40, 200, 55], "agrees": 0.25},
            {"n": 3, "type": "picture", "text": "1 EA CLOSER 5100", "bbox": [10, 60, 200, 75], "agrees": None},
        ],
    }]
    markdown, index = digest.render_document(doc, pages)
    assert "## Page 12 — HARDWARE SET NO. 3" in markdown
    assert "<!-- p12 b2 [10.0, 40.0, 200.0, 55.0] -->" in markdown
    assert "**UNVERIFIED (25% on sheet)** 3 EA HINGE BB1279 US26D" in markdown
    assert "**FROM IMAGE** 1 EA CLOSER 5100" in markdown
    assert "## HARDWARE SET NO. 3\n" in markdown  # an agreeing block is carried as read
    assert index == ["| A6.0 Door Schedule.pdf | 12 | HARDWARE SET NO. 3 | nemotron-parse | 3 | 2 |"]


def test_agreement_catches_a_part_number_the_sheet_does_not_have():
    words = [(10, 40, 30, 50, "3"), (32, 40, 50, 50, "EA"), (52, 40, 80, 50, "HINGE"), (82, 40, 120, 50, "BB1191")]
    right = {"text": "3 EA HINGE BB1191", "bbox": [5, 35, 125, 55]}
    wrong = {"text": "3 EA HINGE BB1279", "bbox": [5, 35, 125, 55]}
    assert page_blocks.agreement(words, right) == 1.0
    assert page_blocks.agreement(words, wrong) == 0.75
    assert page_blocks.agreement(words, {"text": "x", "bbox": [500, 500, 600, 600]}) is None
    assert page_blocks.agreement([], right) is None
    assert page_blocks.agreement(words, {"text": "\\hline 3 & EA", "bbox": [5, 35, 125, 55]}) == 1.0


def test_nim_is_a_parse_provider_with_its_own_key(monkeypatch):
    monkeypatch.setenv("PARSER_PROVIDER", "nim")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-test")
    monkeypatch.delenv("PARSER_API_KEY", raising=False)
    resolved, sources = parsing_config.resolve({})
    assert resolved["provider"] == "nim" and sources["provider"] == "env"
    assert parsing_config.api_key(resolved) == "nvapi-test"
    assert parsing_config.enabled(resolved)
    assert resolved["nimRpm"] == 40 and resolved["nimModel"] == "nvidia/nemotron-parse"
    public = parsing_config.public_config({})
    assert public["fields"]["nimApiKey"]["value"] == "set"
    assert parsing_config.validate({"provider": "gemini"}) == ["provider must be one of ('llamaparse', 'nim')"]
