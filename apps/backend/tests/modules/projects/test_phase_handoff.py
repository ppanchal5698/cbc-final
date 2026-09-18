"""Validated artifact state survives split jobs without reusing stale outputs."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest

from cbc.modules.extraction.api import passes
from cbc.modules.projects.api import pipeline


def phase(tmp_path, name, relative, content="{}"):
    target = tmp_path / "bid" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {name: {"passed": True, "artifacts": {
        relative: hashlib.sha256(content.encode()).hexdigest(),
    }}}


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", ["match_and_price", "build_proposal", "run_full_pipeline"])
async def test_split_jobs_inherit_validated_artifacts(tmp_path, monkeypatch, job_type):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    state = phase(tmp_path, "extraction", "extracted/door_schedule.json")
    project = {"_id": "bid-id", "slug": "bid", "code": "CBC-7"}
    monkeypatch.setattr(pipeline.lookup, "get", AsyncMock(return_value=project))
    monkeypatch.setattr(pipeline.storage, "scaffold", lambda _: None)
    monkeypatch.setattr(pipeline.saga, "set_state", AsyncMock())
    for name in ("defer_if_bid_busy", "defer_if_parsing", "defer_if_catalog_parsing"):
        monkeypatch.setattr(pipeline.ops_worker, name, AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline.ops_jobs, "previous_phase_state", AsyncMock(return_value={"phaseState": state}))
    saved = AsyncMock()
    monkeypatch.setattr(pipeline.ops_jobs, "set_fields", saved)
    run = AsyncMock()
    monkeypatch.setattr(pipeline.claude_pass, "run", run)
    job = {"_id": "next-job", "type": job_type, "projectId": "bid-id"}

    await pipeline.run_pass(job, sync=AsyncMock())

    assert run.call_args.args[0]["phaseState"] == state
    saved.assert_awaited_once_with("next-job", {"phaseState": state})


@pytest.mark.asyncio
async def test_later_pass_keeps_upstream_state_but_drops_failed_and_stale_phases(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    extraction = phase(tmp_path, "extraction", "extracted/door_schedule.json")
    pricing = phase(tmp_path, "pricing", "priced/line_items.json")
    proposal = phase(tmp_path, "proposal", "quotation.html")
    saved = AsyncMock()
    monkeypatch.setattr(passes.ops_jobs, "set_fields", saved)
    job = {"_id": "pricing-job", "type": "match_and_price", "phaseState": {**extraction, **pricing, **proposal}}

    await passes._persist_phase_state(job, "bid", {})
    assert job["phaseState"] == extraction  # Failed pricing must not inherit its old success.

    await passes._persist_phase_state(job, "bid", pricing)
    assert job["phaseState"] == {**extraction, **pricing}
    (tmp_path / "bid/extracted/door_schedule.json").write_text('{"changed":true}')
    await passes._persist_phase_state(job, "bid", pricing)
    assert job["phaseState"] == pricing


@pytest.mark.asyncio
async def test_handoff_drops_artifacts_changed_since_previous_job(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    state = phase(tmp_path, "pricing", "priced/line_items.json")
    (tmp_path / "bid/priced/line_items.json").write_text('{"lines":[]}')
    monkeypatch.setattr(pipeline.ops_jobs, "previous_phase_state", AsyncMock(return_value={"phaseState": state}))
    monkeypatch.setattr(pipeline.ops_jobs, "set_fields", AsyncMock())
    job = {"_id": "next-job"}
    await pipeline._inherit_phase_state(job, {"_id": "bid-id", "slug": "bid"})
    assert job["phaseState"] == {}
