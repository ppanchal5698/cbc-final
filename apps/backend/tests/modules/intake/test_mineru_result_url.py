"""MinerU completed status stubs must fetch result_url, not mark parsed empty."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cbc.modules.intake.features import ParseDocument as parse_doc
from cbc.modules.ops.api import mineru_blocks


def test_looks_like_middle_rejects_status_stub() -> None:
    stub = {
        "task_id": "1d04c2a9-767b-49b3-8083-d6983db86179",
        "status": "completed",
        "result_url": "http://mineru:8000/tasks/1d04c2a9/result",
        "error": None,
    }
    assert mineru_blocks.looks_like_middle(stub) is False


def test_looks_like_middle_accepts_pdf_info() -> None:
    payload = {"pdf_info": [{"page_size": [612, 792], "para_blocks": []}]}
    assert mineru_blocks.looks_like_middle(payload) is True


def test_looks_like_middle_accepts_middle_json_wrapper() -> None:
    payload = {"middle_json": {"pdf_info": [{"page_size": [612, 792]}]}}
    assert mineru_blocks.looks_like_middle(payload) is True


@pytest.mark.asyncio
async def test_completed_middle_fetches_result_url() -> None:
    stub = {
        "task_id": "abc",
        "status": "completed",
        "result_url": "http://mineru:8000/tasks/abc/result",
    }
    middle = {"pdf_info": [{"page_size": [612, 792], "para_blocks": []}]}

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=middle)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)

    result = await parse_doc._completed_middle(
        client, stub, start_page=1, end_page=8
    )

    assert result is middle
    client.get.assert_awaited_once_with("http://mineru:8000/tasks/abc/result")


@pytest.mark.asyncio
async def test_completed_middle_rejects_empty_result_url_payload() -> None:
    stub = {
        "status": "completed",
        "result_url": "http://mineru:8000/tasks/abc/result",
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"status": "completed", "task_id": "abc"})

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)

    with pytest.raises(parse_doc.ParseRetryable, match="no page content"):
        await parse_doc._completed_middle(client, stub, start_page=1, end_page=8)


def test_looks_like_middle_accepts_results_envelope() -> None:
    payload = {
        "backend": "pipeline",
        "version": "2.0.0",
        "results": {
            "set.pdf": {
                "md_content": "# x",
                "middle_json": {"pdf_info": [{"page_size": [612, 792]}]},
            }
        },
    }
    assert mineru_blocks.looks_like_middle(payload) is True
    unwrapped = mineru_blocks.unwrap_mineru_payload(payload)
    assert "middle_json" in unwrapped


@pytest.mark.asyncio
async def test_completed_middle_unwraps_results_envelope() -> None:
    stub = {
        "status": "completed",
        "result_url": "http://mineru:8000/tasks/abc/result",
    }
    envelope = {
        "backend": "pipeline",
        "results": {
            "set.pdf": {"middle_json": {"pdf_info": [{"page_size": [612, 792], "para_blocks": []}]}}
        },
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=envelope)
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)

    result = await parse_doc._completed_middle(client, stub, start_page=1, end_page=8)

    assert "middle_json" in result
    assert mineru_blocks.looks_like_middle(result)


@pytest.mark.asyncio
async def test_completed_middle_rejects_stub_without_result_url() -> None:
    stub: dict[str, Any] = {"status": "completed", "task_id": "abc"}
    client = AsyncMock(spec=httpx.AsyncClient)

    with pytest.raises(parse_doc.ParseRetryable, match="status stub"):
        await parse_doc._completed_middle(client, stub, start_page=1, end_page=8)
    client.get.assert_not_called()

