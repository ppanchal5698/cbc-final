"""Extraction waits for parsing when a key is set; otherwise Claude runs immediately."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cbc.modules.ops.api import worker


@pytest.fixture(autouse=True)
def _clear_parse_bind():
    worker.bind_parse_status(incomplete_parses=AsyncMock(return_value=[]))
    yield
    worker.bind_parse_status(incomplete_parses=AsyncMock(return_value=[]))


@pytest.mark.asyncio
async def test_defer_while_parse_job_queued():
    job = {
        "_id": "extract1",
        "type": "extract_bid_set",
        "projectId": "proj1",
        "status": "running",
        "workerId": "w1",
        "claimGeneration": 1,
        "createdAt": datetime.now(timezone.utc),
    }
    parse_job = {
        "_id": "parse1",
        "type": "parse_document",
        "payload": {"filename": "plans.pdf"},
        "status": "queued",
    }

    with (
        patch.object(worker, "settings_collection") as settings_col,
        patch.object(worker, "jobs_collection") as jobs_col,
        patch("cbc.modules.ops.api.parsing_config.resolve") as resolve,
        patch("cbc.modules.ops.api.parsing_config.enabled", return_value=True),
    ):
        settings_col.return_value.find_one = AsyncMock(return_value={})
        resolve.return_value = (
            {"apiKey": "llx-test", "waitMaxSeconds": 1800},
            {},
        )
        jobs = MagicMock()
        jobs.find_one = AsyncMock(return_value=parse_job)
        jobs.update_one = AsyncMock()
        jobs_col.return_value = jobs

        other = await worker.defer_if_parsing(job)
        assert other is parse_job
        jobs.update_one.assert_awaited()
        note = jobs.update_one.await_args.args[1]["$set"]["note"]
        assert "waiting for plans.pdf to be parsed" in note
        assert jobs.update_one.await_args.args[1]["$inc"]["attempts"] == -1


@pytest.mark.asyncio
async def test_still_waits_after_wait_max_while_parse_running():
    """Claude must not start while a parse is still working, even past wait_max."""
    job = {
        "_id": "extract1",
        "type": "extract_bid_set",
        "projectId": "proj1",
        "status": "running",
        "workerId": "w1",
        "claimGeneration": 1,
        "createdAt": datetime.now(timezone.utc) - timedelta(seconds=2000),
    }
    parse_job = {
        "_id": "parse1",
        "type": "parse_document",
        "payload": {"filename": "plans.pdf"},
        "status": "running",
    }

    with (
        patch.object(worker, "settings_collection") as settings_col,
        patch.object(worker, "jobs_collection") as jobs_col,
        patch("cbc.modules.ops.api.parsing_config.resolve") as resolve,
        patch("cbc.modules.ops.api.parsing_config.enabled", return_value=True),
    ):
        settings_col.return_value.find_one = AsyncMock(return_value={})
        resolve.return_value = (
            {"apiKey": "llx-test", "waitMaxSeconds": 1800},
            {},
        )
        jobs = MagicMock()
        jobs.find_one = AsyncMock(return_value=parse_job)
        jobs.update_one = AsyncMock()
        jobs_col.return_value = jobs

        other = await worker.defer_if_parsing(job)
        assert other is parse_job
        jobs.update_one.assert_awaited()
        note = jobs.update_one.await_args.args[1]["$set"]["note"]
        assert "waiting for plans.pdf to be parsed" in note


@pytest.mark.asyncio
async def test_defer_while_document_parse_incomplete_even_without_job():
    """Document parse.state queued/running blocks Claude even if the job row is gone."""
    job = {
        "_id": "extract1",
        "type": "extract_bid_set",
        "projectId": "proj1",
        "status": "running",
        "workerId": "w1",
        "claimGeneration": 1,
        "createdAt": datetime.now(timezone.utc),
    }
    pending = [{"_id": "doc1", "filename": "A1.pdf", "parse": {"state": "queued"}}]
    worker.bind_parse_status(incomplete_parses=AsyncMock(return_value=pending))

    with (
        patch.object(worker, "settings_collection") as settings_col,
        patch.object(worker, "jobs_collection") as jobs_col,
        patch("cbc.modules.ops.api.parsing_config.resolve") as resolve,
        patch("cbc.modules.ops.api.parsing_config.enabled", return_value=True),
    ):
        settings_col.return_value.find_one = AsyncMock(return_value={})
        resolve.return_value = ({"apiKey": "llx-test", "waitMaxSeconds": 1800}, {})
        jobs = MagicMock()
        jobs.find_one = AsyncMock(return_value=None)
        jobs.update_one = AsyncMock()
        jobs_col.return_value = jobs

        other = await worker.defer_if_parsing(job)
        assert other is not None
        note = jobs.update_one.await_args.args[1]["$set"]["note"]
        assert "waiting for A1.pdf to be parsed" in note


@pytest.mark.asyncio
async def test_no_defer_when_parsing_off():
    job = {
        "_id": "extract1",
        "type": "extract_bid_set",
        "projectId": "proj1",
        "status": "running",
        "createdAt": datetime.now(timezone.utc),
    }
    with (
        patch.object(worker, "settings_collection") as settings_col,
        patch("cbc.modules.ops.api.parsing_config.resolve") as resolve,
        patch("cbc.modules.ops.api.parsing_config.enabled", return_value=False),
    ):
        settings_col.return_value.find_one = AsyncMock(return_value={})
        resolve.return_value = ({"url": ""}, {})
        assert await worker.defer_if_parsing(job) is None


@pytest.mark.asyncio
async def test_no_defer_when_parse_finished():
    job = {
        "_id": "extract1",
        "type": "extract_bid_set",
        "projectId": "proj1",
        "status": "running",
        "workerId": "w1",
        "claimGeneration": 1,
        "createdAt": datetime.now(timezone.utc),
    }
    with (
        patch.object(worker, "settings_collection") as settings_col,
        patch.object(worker, "jobs_collection") as jobs_col,
        patch("cbc.modules.ops.api.parsing_config.resolve") as resolve,
        patch("cbc.modules.ops.api.parsing_config.enabled", return_value=True),
    ):
        settings_col.return_value.find_one = AsyncMock(return_value={})
        resolve.return_value = ({"apiKey": "llx-test", "waitMaxSeconds": 1800}, {})
        jobs = MagicMock()
        jobs.find_one = AsyncMock(return_value=None)  # no active parse job
        jobs.update_one = AsyncMock()
        jobs_col.return_value = jobs
        # incomplete_parses fixture returns []
        assert await worker.defer_if_parsing(job) is None
        jobs.update_one.assert_not_awaited()
