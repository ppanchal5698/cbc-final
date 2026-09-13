"""WORKER_CONCURRENCY: parse helper and overlapping process() slots."""
from __future__ import annotations

import asyncio
import re

from cbc.modules.ops.features.WorkerLoop import concurrency_for
from tests.shared import ROOT


def test_concurrency_for_rejects_junk_and_zero() -> None:
    assert concurrency_for("2") == 2
    assert concurrency_for("0") == 1
    assert concurrency_for("-3") == 1
    assert concurrency_for("nope") == 1
    assert concurrency_for("") == 1


def test_compose_worker_has_no_fixed_container_name() -> None:
    body = (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    # Exact service name â€” do not match a substring of another container_name.
    assert re.search(r"(?m)^\s*container_name:\s*cbc-worker\s*$", body) is None
    assert re.search(r"WORKER_CONCURRENCY:", body)


def test_loop_starts_second_job_before_first_finishes(monkeypatch) -> None:
    from cbc.modules.ops.api import worker as ops_worker
    from cbc.modules.ops.features import WorkerLoop as worker

    started: list[str] = []

    async def drive() -> None:
        both = asyncio.Event()
        jobs = [
            {"_id": "a", "type": "match_and_price"},
            {"_id": "b", "type": "match_and_price"},
        ]

        async def fake_claim():
            return jobs.pop(0) if jobs else None

        async def fake_process(job):
            started.append(str(job["_id"]))
            if len(started) >= 2:
                both.set()
                ops_worker._stop.set()
            await both.wait()

        async def fake_reap():
            return 0

        monkeypatch.setattr(worker, "claim", fake_claim)
        monkeypatch.setattr(worker, "process", fake_process)
        monkeypatch.setattr(worker, "reap_abandoned", fake_reap)
        monkeypatch.setattr(worker, "concurrency_for", lambda: 2)
        ops_worker._stop = asyncio.Event()
        try:
            await asyncio.wait_for(worker.loop(once=False), timeout=3)
        finally:
            ops_worker._stop = asyncio.Event()

    asyncio.run(drive())
    assert set(started) == {"a", "b"}

