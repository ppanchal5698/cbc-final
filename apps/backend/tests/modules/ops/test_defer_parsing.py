"""Extraction waits for parsing when a key is set; otherwise Claude runs immediately."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cbc.modules.ops.api import worker


class _Rows:
    """An async cursor over a few job rows."""

    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def rows():
            for row in self.rows:
                yield row
        return rows()


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


def _stuck_parse(uploaded_seconds_ago: int):
    """An extract on a bid whose one document has been parsing since its upload."""
    job = {
        "_id": "extract1",
        "type": "extract_bid_set",
        "projectId": "proj1",
        "status": "running",
        "workerId": "w1",
        "claimGeneration": 1,
        # Enqueued just now: the clock runs from the upload, not from this job.
        "createdAt": datetime.now(timezone.utc),
    }
    parse_job = {
        "_id": "parse1",
        "type": "parse_document",
        "payload": {"filename": "plans.pdf", "documentId": "doc1"},
        "status": "running",
    }
    uploaded = datetime.now(timezone.utc) - timedelta(seconds=uploaded_seconds_ago)
    pending = [{"_id": "doc1", "filename": "plans.pdf", "parse": {"state": "running"}, "uploadedAt": uploaded}]
    return job, parse_job, pending


async def _defer(job, parse_job, pending, expire):
    worker.bind_parse_status(incomplete_parses=AsyncMock(return_value=pending), expire_parse=expire)
    with (
        patch.object(worker, "settings_collection") as settings_col,
        patch.object(worker, "jobs_collection") as jobs_col,
        patch("cbc.modules.ops.api.parsing_config.resolve") as resolve,
        patch("cbc.modules.ops.api.parsing_config.enabled", return_value=True),
    ):
        settings_col.return_value.find_one = AsyncMock(return_value={})
        resolve.return_value = ({"apiKey": "llx-test", "waitMaxSeconds": 1800}, {})
        jobs = MagicMock()
        jobs.find_one = AsyncMock(return_value=parse_job)
        jobs.find = MagicMock(return_value=_Rows([parse_job]))
        jobs.update_one = AsyncMock()
        jobs.update_many = AsyncMock()
        jobs_col.return_value = jobs
        return await worker.defer_if_parsing(job), jobs


@pytest.mark.asyncio
async def test_still_waits_past_wait_max_but_short_of_twice_it():
    """Between wait_max and twice it, a parse still working holds the extract."""
    job, parse_job, pending = _stuck_parse(2000)
    expire = AsyncMock()

    other, jobs = await _defer(job, parse_job, pending, expire)

    assert other is parse_job
    note = jobs.update_one.await_args.args[1]["$set"]["note"]
    assert "waiting for plans.pdf to be parsed" in note
    jobs.update_many.assert_not_awaited()
    expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_released_at_twice_wait_max_with_the_parse_given_up():
    """A parse worker that never finishes no longer holds the bid for ever."""
    job, parse_job, pending = _stuck_parse(3700)
    expire = AsyncMock()

    other, jobs = await _defer(job, parse_job, pending, expire)

    assert other is None, "the extract must proceed"
    jobs.update_one.assert_not_awaited()  # not requeued
    query, update = jobs.update_many.await_args.args
    assert query["projectId"] == "proj1" and query["type"] == "parse_document"
    assert query["status"] == {"$in": ["queued", "running"]}
    assert update["$set"]["status"] == "cancelled"
    expire.assert_awaited_once_with("doc1", "parse deadline exceeded")


@pytest.mark.asyncio
async def test_a_document_no_parse_job_will_read_is_let_go_at_once():
    """A parse cancelled in the queue left its document `queued` with no job to read
    it, and the extract waited the hour it takes to give up. It is expired now -
    read from the PDF itself - and the extract goes on."""
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
    expire = AsyncMock()
    worker.bind_parse_status(incomplete_parses=AsyncMock(return_value=pending), expire_parse=expire)

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
        jobs.find = MagicMock(return_value=_Rows([]))
        jobs.update_one = AsyncMock()
        jobs_col.return_value = jobs

        assert await worker.defer_if_parsing(job) is None
        expire.assert_awaited_once_with("doc1", "no parse job left to read it")
        jobs.update_one.assert_not_awaited()


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
