"""POST /api/settings/parsing/test against a stubbed LlamaParse.

The route's value is that it reports `verified` - the share of returned boxes
sitting on text actually present on a page whose layout we generated. A frame or
orientation regression shows there before any bid is parsed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cbc.modules.ops.api import llamaparse
from cbc.modules.ops.features import TestParsingSettings as mod


def _isolate(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    from cbc.modules.ops.api import parsing_config

    for key in parsing_config.FIELDS.values():
        monkeypatch.delenv(key, raising=False)


def _one_page(pdf_page_size=(612.0, 792.0)):
    """A block sitting on the sample's heading, so verify_page can score it."""
    width, height = pdf_page_size
    return [{
        "page": 1,
        "width": width,
        "height": height,
        "items": [{
            "type": "text",
            "text": "CBC Parser Test Page",
            "bbox": [70.0, 58.0, 260.0, 78.0],
        }],
    }]


@pytest.mark.asyncio
async def test_test_route_reports_blocks_and_verified(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"apiKey": "llx-key"})),
        patch.object(llamaparse, "upload", AsyncMock(return_value="file-1")),
        patch.object(llamaparse, "parse_window", AsyncMock(return_value=_one_page())),
    ):
        result = await mod.test_parsing_settings(mod.ParsingTestBody(tier="agentic"))

    assert result["ok"] is True
    assert result["tier"] == "agentic"
    assert result["blocks"] == 1
    # The generated sample has a text layer, so this is a real number, not None.
    assert result["verified"] is not None
    assert result["error"] is None


@pytest.mark.asyncio
async def test_test_route_reports_a_rejected_key_plainly(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"apiKey": "llx-bad"})),
        patch.object(
            llamaparse, "upload",
            AsyncMock(side_effect=llamaparse.ParsePermanent("file upload failed (401): nope")),
        ),
    ):
        result = await mod.test_parsing_settings(mod.ParsingTestBody())

    assert result["ok"] is False
    assert "API key" in result["error"]


@pytest.mark.asyncio
async def test_test_route_marks_a_transient_failure_as_retryable(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"apiKey": "llx-key"})),
        patch.object(
            llamaparse, "upload",
            AsyncMock(side_effect=llamaparse.ParseRetryable("file upload failed (503): down")),
        ),
    ):
        result = await mod.test_parsing_settings(mod.ParsingTestBody())

    assert result["ok"] is False
    assert "retry" in result["error"].lower()


@pytest.mark.asyncio
async def test_test_route_rejects_the_fast_tier_before_calling_out(monkeypatch, tmp_path):
    """400 at the edge: `fast` returns no boxes, so there is nothing to test."""
    from fastapi import HTTPException

    _isolate(monkeypatch, tmp_path)

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"apiKey": "llx-key"})),
        patch.object(llamaparse, "upload", AsyncMock()) as upload,
    ):
        with pytest.raises(HTTPException) as err:
            await mod.test_parsing_settings(mod.ParsingTestBody(tier="fast"))
        assert err.value.status_code == 400
        upload.assert_not_called()


@pytest.mark.asyncio
async def test_test_route_says_so_when_parsing_is_off(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    with patch.object(mod, "load_config", AsyncMock(return_value={})):
        result = await mod.test_parsing_settings(mod.ParsingTestBody())

    assert result["ok"] is False
    assert "PARSER_API_KEY" in result["error"]
