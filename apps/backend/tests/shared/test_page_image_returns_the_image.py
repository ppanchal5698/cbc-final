"""Seeing a page costs one turn, not two.

`get_page_image` returned `{"image_path": ...}` and nothing else, so the model
had to `Read` the file to actually see it. Every look cost two turns and left the
image in context for every later turn.

Measured on one 24-page bid: the take-off leg spent 48 of its 80 tool calls on
`get_page_image` -> `Read` pairs, rendered two sheets twenty-four times, and hit
its 80-turn cap - which means the verification was cut short. The round trip was
costing accuracy, not just money.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import fitz
import pytest

from tests.shared import ROOT

SERVER = ROOT / "mcp-servers" / "pdf-tools" / "server.py"


@pytest.fixture(scope="module")
def pdf_tools():
    """Import the server the way the MCP host does - by path, with its own dir."""
    for extra in (str(SERVER.parent), str(ROOT / "mcp-servers")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    spec = importlib.util.spec_from_file_location("pdf_tools_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def one_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "DOOR SCHEDULE")
    path = tmp_path / "sheet.pdf"
    doc.save(path)
    doc.close()
    return path


def test_the_image_comes_back_with_the_metadata(pdf_tools, one_page):
    hit = pdf_tools.get_page_image(str(one_page), 1, dpi=150)

    assert "_image" in hit, "the render returned a path and no image"
    assert hit["_image"]["mimeType"] == "image/png"
    decoded = base64.b64decode(hit["_image"]["data"])
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"

    # The path stays: `visual_pages_checked` cites it, and the render cache is
    # keyed on it.
    assert hit.get("image_path")
    # And the numbers that tell the caller whether a re-crop is worth trying.
    assert "px_per_pt" in hit and "legible" in hit


def test_the_runtime_sends_it_as_an_image_block():
    """`_image` has to leave the runtime as ImageContent, not as text."""
    sys.path.insert(0, str(ROOT / "mcp-servers"))
    from _runtime import result_content  # noqa: E402

    blocks = result_content(
        {"image_path": "/tmp/x.png", "_image": {"data": "Zm9v", "mimeType": "image/png"}}
    )

    kinds = [b.type for b in blocks]
    assert "image" in kinds, f"the image was not sent as an image block: {kinds}"
    assert "text" in kinds, "the metadata must still come back"

    text = next(b.text for b in blocks if b.type == "text")
    assert "_image" not in text, "transport key leaked into the payload"
    assert "image_path" in text, "the path is still needed for visual_pages_checked"


def test_a_handler_that_renders_nothing_is_unchanged():
    sys.path.insert(0, str(ROOT / "mcp-servers"))
    from _runtime import result_content  # noqa: E402

    blocks = result_content({"rows": [1, 2]})
    assert [b.type for b in blocks] == ["text"]
