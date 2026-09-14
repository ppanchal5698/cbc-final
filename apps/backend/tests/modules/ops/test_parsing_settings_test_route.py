"""POST /api/settings/parsing/test against a fake MinerU."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cbc.modules.ops.features import TestParsingSettings as mod


@pytest.mark.asyncio
async def test_test_route_success(monkeypatch, tmp_path):
    monkeypatch.setenv("CBC_ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / ".env").write_text("", encoding="utf-8")

    parse_resp = MagicMock()
    parse_resp.is_success = True
    parse_resp.raise_for_status = MagicMock()
    parse_resp.json.return_value = {
        "pdf_info": [{"para_blocks": [{"type": "text", "bbox": [0, 0, 1, 1], "lines": []}]}]
    }
    health_resp = MagicMock()
    health_resp.is_success = True
    health_resp.json.return_value = {"version": "3.4.0"}

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=parse_resp)
    client.get = AsyncMock(return_value=health_resp)

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"url": "http://mineru:8000", "profile": "low"})),
        patch("httpx.AsyncClient", return_value=client),
    ):
        result = await mod.test_parsing_settings(
            mod.ParsingTestBody(url="http://mineru:8000", backend="pipeline", profile="low")
        )
    assert result["ok"] is True
    assert result["version"] == "3.4.0"
    assert result["blocks"] >= 0


@pytest.mark.asyncio
async def test_test_route_unreachable(monkeypatch, tmp_path):
    monkeypatch.setenv("CBC_ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / ".env").write_text("", encoding="utf-8")

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"url": "http://mineru:8000"})),
        patch("httpx.AsyncClient", return_value=client),
    ):
        result = await mod.test_parsing_settings(
            mod.ParsingTestBody(url="http://mineru:8000", backend="pipeline")
        )
    assert result["ok"] is False
    assert "unreachable" in (result["error"] or "").lower() or "connect" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_test_route_bad_backend_400(monkeypatch, tmp_path):
    monkeypatch.setenv("CBC_ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / ".env").write_text("", encoding="utf-8")

    parse_resp = MagicMock()
    parse_resp.status_code = 400
    parse_resp.text = "unknown backend"
    parse_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("bad", request=MagicMock(), response=parse_resp)
    )

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=parse_resp)

    with (
        patch.object(mod, "load_config", AsyncMock(return_value={"url": "http://mineru:8000"})),
        patch("httpx.AsyncClient", return_value=client),
    ):
        result = await mod.test_parsing_settings(
            mod.ParsingTestBody(url="http://mineru:8000", backend="pipeline")
        )
    assert result["ok"] is False
    assert "400" in (result["error"] or "")
