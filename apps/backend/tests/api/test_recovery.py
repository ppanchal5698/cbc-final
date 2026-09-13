"""Concurrency and recovery, against a real MongoDB.

Everything here is a production failure mode that local development never
reproduces: a worker killed mid-run, two estimators clicking at the same moment,
two vendors selling the same part number. They need the real indexes, so they
need the real database.

    docker compose up -d mongo && python -m pytest tests/api/test_recovery.py -q
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from pymongo import MongoClient

from cbc.app.main import migrate_and_index
from cbc.shared import mongo as shared_mongo
from cbc.shared.config import settings
from tests.shared import mongo_client
from cbc.persistence import names

TEST_DB = "cbc_opshub_test_recovery"


@pytest.fixture()
def database():
    """A throwaway database with the real indexes built on it."""
    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw.server_info()
    except Exception as exc:
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(f"REQUIRE_MONGO is set but MongoDB is not reachable: {exc}")
        pytest.skip("MongoDB is not running - start it with `docker compose up -d mongo`")

    previous, settings.mongodb_db = settings.mongodb_db, TEST_DB
    raw.drop_database(TEST_DB)
    shared_mongo._client = None

    asyncio.run(migrate_and_index())  # every module's indexes, not only the legacy set
    shared_mongo._client = None
    try:
        yield raw[TEST_DB]
    finally:
        raw.drop_database(TEST_DB)
        raw.close()
        settings.mongodb_db = previous
        shared_mongo._client = None


def run(coro):
    """Each test gets its own loop, so the motor client binds to it."""
    shared_mongo._client = None
    try:
        return asyncio.run(coro)
    finally:
        shared_mongo._client = None


def _now():
    return datetime.now(timezone.utc)


# â”€â”€ a killed worker must not wedge the bid forever â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_stale_running_job_is_reaped_and_requeued(database) -> None:
    """`running` with no heartbeat means the process that claimed it is gone.

    Left alone the job stays `running` for ever, and because the exclusive-job
    index counts it as in flight, that bid can never be re-extracted again.
    """
    from bson import ObjectId

    project_id = ObjectId()
    database["jobs"].insert_one(
        {
            "type": "extract_bid_set",
            "projectId": project_id,
            "status": "running",
            "attempts": 1,
            "createdAt": _now(),
            "heartbeatAt": _now() - timedelta(minutes=20),
        }
    )

    from cbc.modules.ops.features.WorkerLoop import reap_abandoned

    assert run(reap_abandoned()) == 1

    job = database["jobs"].find_one({"projectId": project_id})
    assert job["status"] == "queued"
    assert job["heartbeatAt"] is None
    assert "worker stopped" in job["error"]


def test_an_extract_job_is_not_reaped_after_three_minutes(database) -> None:
    """Extract stale window is 10 minutes; a 90s global cutoff used to steal live runs."""
    from bson import ObjectId

    from cbc.modules.ops.features.WorkerLoop import reap_abandoned

    database["jobs"].insert_one(
        {
            "type": "extract_bid_set",
            "projectId": ObjectId(),
            "status": "running",
            "attempts": 1,
            "createdAt": _now(),
            "heartbeatAt": _now() - timedelta(minutes=3),
        }
    )
    assert run(reap_abandoned()) == 0
    assert database["jobs"].find_one({})["status"] == "running"


def test_import_extraction_aborts_when_the_lease_was_stolen(database, monkeypatch, tmp_path) -> None:
    from bson import ObjectId

    from cbc.shared.config import settings
    from cbc.modules.extraction.api import door_schedule
    from cbc.shared import storage

    previous = settings.storage_root
    settings.storage_root = tmp_path
    slug = "lease_stolen"
    storage.scaffold(slug)
    path = tmp_path / slug / "extracted" / "door_schedule.json"
    path.write_text(
        '{"openings":[{"door_number":"101","size":"3070","source_page":1}]}',
        encoding="utf-8",
    )
    job_id = ObjectId()
    project_id = ObjectId()
    database["jobs"].insert_one(
        {
            "_id": job_id,
            "type": "extract_bid_set",
            "projectId": project_id,
            "status": "running",
            "workerId": "a",
            "claimGeneration": 1,
        }
    )
    database["jobs"].update_one(
        {"_id": job_id}, {"$set": {"workerId": "b", "claimGeneration": 2}}
    )
    project = {"_id": project_id, "slug": slug, "code": "LS-1"}
    try:
        counts = run(
            door_schedule.import_extraction(
                project,
                job={"_id": job_id, "workerId": "a", "claimGeneration": 1},
            )
        )
    finally:
        settings.storage_root = previous
    assert counts.get("aborted") is True
    assert database[names.OPENINGS].count_documents({}) == 0


def test_a_job_with_a_fresh_heartbeat_is_left_alone(database) -> None:
    """Another worker is genuinely running it. Reaping would double-run the bid."""
    from bson import ObjectId

    database["jobs"].insert_one(
        {
            "type": "match_and_price",
            "projectId": ObjectId(),
            "status": "running",
            "attempts": 1,
            "createdAt": _now(),
            "heartbeatAt": _now(),
        }
    )

    from cbc.modules.ops.features.WorkerLoop import reap_abandoned

    assert run(reap_abandoned()) == 0
    assert database["jobs"].find_one({})["status"] == "running"


def test_only_one_active_pipeline_job_per_project(database) -> None:
    """Autopilot and manual pricing must not run as two Claude sessions on one bid."""
    from bson import ObjectId

    from cbc.modules.ops.api import jobs

    project_id = ObjectId()
    autopilot = run(jobs.enqueue("run_full_pipeline", project_id))
    pricing = run(jobs.enqueue("match_and_price", project_id))

    assert pricing["_id"] == autopilot["_id"]
    assert pricing["type"] == "run_full_pipeline"
    assert (
        database["jobs"].count_documents(
            {
                "projectId": project_id,
                "status": {"$in": ["queued", "running"]},
            }
        )
        == 1
    )


def test_enqueue_exclusive_refuses_a_second_pipeline_type(database) -> None:
    from bson import ObjectId

    from cbc.modules.ops.api import jobs

    project_id = ObjectId()
    run(jobs.enqueue("extract_bid_set", project_id))

    with pytest.raises(jobs.PipelineJobActive):
        run(jobs.enqueue_exclusive("match_and_price", project_id))


def test_a_reaped_job_that_is_out_of_attempts_fails(database) -> None:
    from bson import ObjectId

    from cbc.modules.ops.features.WorkerLoop import MAX_ATTEMPTS, reap_abandoned

    database["jobs"].insert_one(
        {
            "type": "extract_bid_set",
            "projectId": ObjectId(),
            "status": "running",
            "attempts": MAX_ATTEMPTS,
            "createdAt": _now(),
            "heartbeatAt": None,
        }
    )

    run(reap_abandoned())
    assert database["jobs"].find_one({})["status"] == "dead"


def test_a_requeued_job_waits_for_its_backoff(database) -> None:
    """Without a delay a job that fails in two seconds burns three attempts in six."""
    from cbc.modules.ops.features.WorkerLoop import claim

    database["jobs"].insert_one(
        {
            "type": "extract_bid_set",
            "projectId": None,
            "status": "queued",
            "attempts": 1,
            "createdAt": _now(),
            "nextAttemptAt": _now() + timedelta(minutes=5),
        }
    )
    assert run(claim()) is None, "claimed a job that is still backing off"

    database["jobs"].update_one({}, {"$set": {"nextAttemptAt": _now() - timedelta(seconds=1)}})
    assert run(claim()) is not None, "a due job was not claimed"


# â”€â”€ the exclusive-job index must encode the same policy as the code â”€â”€â”€â”€â”€â”€â”€â”€


def test_two_price_book_ingests_can_queue_together(database) -> None:
    """Both carry no project, so the old index keyed them both on (null, type).

    The second upload was handed back the first one's job and its sheet was never
    read - while the API reported success.
    """
    from cbc.modules.ops.api.jobs import enqueue

    async def both():
        return (
            await enqueue("ingest_pricebook", payload={"filename": "hager.pdf"}),
            await enqueue("ingest_pricebook", payload={"filename": "rockwood.pdf"}),
        )

    first, second = run(both())

    assert first["_id"] != second["_id"], "the second price book was silently dropped"
    assert database["jobs"].count_documents({"type": "ingest_pricebook"}) == 2


def test_a_second_extraction_on_one_bid_is_still_the_same_job(database) -> None:
    """The double-click guard this index exists for still has to work."""
    from bson import ObjectId

    from cbc.modules.ops.api.jobs import enqueue

    project_id = ObjectId()

    async def twice():
        return (
            await enqueue("extract_bid_set", project_id=project_id),
            await enqueue("extract_bid_set", project_id=project_id),
        )

    first, second = run(twice())
    assert first["_id"] == second["_id"]


# â”€â”€ two vendors, one part number â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_the_same_part_from_two_manufacturers_coexists(database) -> None:
    """Keyed on `part` alone, the ingest upserted one vendor's row over another's."""
    from bson import ObjectId

    from cbc.modules.catalog.features.IngestPricebook import ingest_pricebook

    cache = settings.repo_root / ".cache"
    cache.mkdir(parents=True, exist_ok=True)

    def sheet(manufacturer: str, cost: float, book_id) -> dict:
        path = cache / f"pricebook-{manufacturer}.json"
        path.write_text(
            f'{{"products": [{{"part": "1234", "manufacturer": "{manufacturer}", '
            f'"cost": {cost}}}]}}',
            encoding="utf-8",
        )
        return {
            "type": "ingest_pricebook",
            "payload": {"outputPath": f".cache/{path.name}", "priceBookId": str(book_id)},
        }

    hager, rockwood = ObjectId(), ObjectId()
    database["priceBooks"].insert_many([{"_id": hager}, {"_id": rockwood}])

    async def both():
        await ingest_pricebook(sheet("Hager", 10.0, hager))
        await ingest_pricebook(sheet("Rockwood", 20.0, rockwood))

    run(both())

    rows = {row["manufacturer"]: row["cost"] for row in database[names.CATALOG_ITEMS].find({"part": "1234"})}
    assert rows == {"Hager": 10.0, "Rockwood": 20.0}


def test_an_ingest_without_a_date_keeps_the_one_purchasing_entered(database) -> None:
    """Writing null over it made a lapsed sheet report `stale: false`."""
    from bson import ObjectId

    from cbc.modules.catalog.features.IngestPricebook import ingest_pricebook

    book_id = ObjectId()
    database["priceBooks"].insert_one({"_id": book_id, "effective": "2020-01-01"})

    cache = settings.repo_root / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "pricebook-undated.json"
    path.write_text('{"products": [{"part": "X1", "manufacturer": "ASI"}]}', encoding="utf-8")

    run(
        ingest_pricebook(
            {
                "type": "ingest_pricebook",
                "payload": {"outputPath": ".cache/pricebook-undated.json",
                            "priceBookId": str(book_id)},
            }
        )
    )

    assert database["priceBooks"].find_one({"_id": book_id})["effective"] == "2020-01-01"


# â”€â”€ numbering under concurrency â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_concurrent_bids_get_distinct_codes(database) -> None:
    """Both used to compute max+1 from a scan; the second got a duplicate-key 500."""
    from cbc.modules.projects.features.CreateProject import next_code

    async def ten_at_once():
        return await asyncio.gather(*(next_code() for _ in range(10)))

    codes = run(ten_at_once())
    assert len(set(codes)) == 10, f"codes collided: {sorted(codes)}"


def test_the_code_counter_continues_an_existing_series(database) -> None:
    """A database issued codes before the counter existed; do not restart on them."""
    from cbc.modules.projects.features.CreateProject import code_prefix, next_code

    prefix = code_prefix()
    database[names.BID_REQUESTS].insert_one({"code": f"{prefix}0007", "slug": "old"})

    assert run(next_code()) == f"{prefix}0008"


def test_two_versions_cannot_share_a_number(database) -> None:
    """Two addenda both became version n+1 and the diff attached to either one."""
    from bson import ObjectId

    from cbc.modules.intake.infrastructure.snapshot import snapshot

    project = {"_id": ObjectId(), "slug": "concurrent-addenda"}

    async def two_snapshots():
        return await asyncio.gather(
            snapshot(project, "Addendum 1", "rick"),
            snapshot(project, "Addendum 2", "shanna"),
        )

    versions = run(two_snapshots())
    assert {v["version"] for v in versions} == {1, 2}


# â”€â”€ one indexing pass per sheet â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_re_uploading_a_sheet_does_not_queue_a_second_index(database) -> None:
    """`index_catalog` carries no project, so per-project exclusivity misses it.

    The price-books screen makes a double upload easy, and two indexing passes
    over one sheet raced to write the same pageIndex document. Indexing is
    idempotent on the file hash, so the second was waste even when it won.
    """
    from cbc.modules.ops.api import jobs

    payload = {"priceBookId": "0" * 24, "filename": "hager_price_book_18.pdf"}
    first = run(jobs.enqueue("index_catalog", payload=dict(payload)))
    second = run(jobs.enqueue("index_catalog", payload=dict(payload)))

    assert first["_id"] == second["_id"]
    assert database["jobs"].count_documents({"type": "index_catalog"}) == 1


def test_a_different_sheet_still_gets_its_own_job(database) -> None:
    from cbc.modules.ops.api import jobs

    first = run(jobs.enqueue("index_catalog", payload={"filename": "rockwood.pdf"}))
    second = run(jobs.enqueue("index_catalog", payload={"filename": "pemko.pdf"}))

    assert first["_id"] != second["_id"]
    assert database["jobs"].count_documents({"type": "index_catalog"}) == 2


def test_a_finished_index_does_not_block_a_re_index(database) -> None:
    """Coalescing is about work in flight. A sheet that changed must re-index."""
    from cbc.modules.ops.api import jobs

    first = run(jobs.enqueue("index_catalog", payload={"filename": "gamco.pdf"}))
    database["jobs"].update_one({"_id": first["_id"]}, {"$set": {"status": "done"}})

    second = run(jobs.enqueue("index_catalog", payload={"filename": "gamco.pdf"}))
    assert first["_id"] != second["_id"]


def test_same_file_sha_coalesces_even_when_filenames_differ(database) -> None:
    from cbc.modules.ops.api import jobs

    first = run(
        jobs.enqueue(
            "index_catalog",
            payload={"filename": "hager.pdf", "fileSha": "sha256:abc"},
        )
    )
    second = run(
        jobs.enqueue(
            "index_catalog",
            payload={"filename": "hager (1).pdf", "fileSha": "sha256:abc"},
        )
    )
    assert first["_id"] == second["_id"]
    assert database["jobs"].count_documents({"type": "index_catalog"}) == 1


def test_a_different_file_sha_still_gets_its_own_job(database) -> None:
    from cbc.modules.ops.api import jobs

    first = run(
        jobs.enqueue(
            "index_catalog",
            payload={"filename": "hager.pdf", "fileSha": "sha256:aaa"},
        )
    )
    second = run(
        jobs.enqueue(
            "index_catalog",
            payload={"filename": "hager.pdf", "fileSha": "sha256:bbb"},
        )
    )
    assert first["_id"] != second["_id"]
    assert database["jobs"].count_documents({"type": "index_catalog"}) == 2


# â”€â”€ the queue, visible without reading the logs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_metrics_report_depth_throughput_and_failures(database) -> None:
    """The only operational view of the queue was `docker logs`."""
    from cbc.modules.ops.api import jobs

    now = _now()
    # Distinct projects: `exclusive_active_job` is a unique partial index over
    # projectId for queued and running pipeline jobs, so two active jobs of any
    # pipeline type on one project is exactly what the schema forbids.
    from bson import ObjectId

    database["jobs"].insert_many([
        {"type": "extract_bid_set", "status": "queued", "createdAt": now,
         "projectId": ObjectId()},
        {"type": "extract_bid_set", "status": "running", "createdAt": now,
         "projectId": ObjectId()},
        {"type": "match_and_price", "status": "done", "createdAt": now,
         "projectId": ObjectId(),
         "startedAt": now, "finishedAt": now + timedelta(seconds=90)},
        {"type": "match_and_price", "status": "failed", "createdAt": now,
         "projectId": ObjectId(),
         "startedAt": now, "finishedAt": now + timedelta(seconds=5)},
    ])

    result = run(jobs.metrics(window_hours=24))

    assert result["queued"] == 1
    assert result["running"] == 1
    assert result["finished"] == 2
    assert result["failed"] == 1
    assert result["failureRate"] == 0.5
    assert result["byType"]["match_and_price"]["avgSeconds"] == 90.0


def test_a_running_job_does_not_drag_the_average_down(database) -> None:
    """It has a startedAt and no finishedAt, so it has no duration yet."""
    from cbc.modules.ops.api import jobs

    now = _now()
    database["jobs"].insert_many([
        {"type": "build_proposal", "status": "done", "createdAt": now,
         "startedAt": now, "finishedAt": now + timedelta(seconds=60)},
        {"type": "build_proposal", "status": "running", "createdAt": now, "startedAt": now},
    ])

    result = run(jobs.metrics())
    assert result["byType"]["build_proposal"]["avgSeconds"] == 60.0


def test_no_finished_jobs_reports_no_rate_rather_than_zero(database) -> None:
    """A 0% failure rate over zero jobs is not good news, it is no news."""
    from cbc.modules.ops.api import jobs

    database["jobs"].insert_one(
        {"type": "extract_bid_set", "status": "queued", "createdAt": _now()}
    )
    result = run(jobs.metrics())
    assert result["failureRate"] is None
    assert result["oldestQueuedAt"] is not None


def test_artifact_validation_failure_is_not_retried(database) -> None:
    """A missing bbox used to re-queue the whole job up to MAX_ATTEMPTS (T-03)."""
    from bson import ObjectId

    from cbc.modules.ops.api import worker

    job_id = ObjectId()
    job = {
        "_id": job_id,
        "type": "extract_bid_set",
        "projectId": ObjectId(),
        "status": "running",
        "attempts": 1,
        "workerId": "test-worker",
        "claimGeneration": 1,
        "payload": {},
    }
    database["jobs"].insert_one(job)

    run(
        worker.finish(
            job,
            False,
            "artifact validation failed: opening 01 has no bbox",
            "",
            permanent=True,
            error_code="artifact_validation",
        )
    )

    stored = database["jobs"].find_one({"_id": job_id})
    assert stored["status"] == "dead"
    assert stored["attempts"] == 1
    assert stored["errorCode"] == "artifact_validation"
    assert "bbox" in stored["error"]
    assert stored.get("nextAttemptAt") is None


def test_a_dead_job_can_be_retried(database) -> None:
    from bson import ObjectId

    from cbc.modules.ops.api import jobs

    job_id = ObjectId()
    project_id = ObjectId()
    database["jobs"].insert_one(
        {
            "_id": job_id,
            "type": "extract_bid_set",
            "projectId": project_id,
            "status": "dead",
            "attempts": 3,
            "error": "artifact validation failed",
            "errorCode": "artifact_validation",
            "claimGeneration": 4,
        }
    )
    updated = run(jobs.retry(job_id, "estimator"))
    assert updated["status"] == "queued"
    assert updated["attempts"] == 0
    assert updated["error"] is None
    assert updated["note"] == "requeued from dead-letter"


# ── what follows a finished job is bound, not imported ───────────────────────


def test_finish_hands_the_outcome_to_the_bound_hook(database, monkeypatch) -> None:
    """ops records how a job ended; what follows belongs to whoever ran it.

    A retry is not an ending: the hook hears about dead and done, never queued.
    """
    from bson import ObjectId

    from cbc.modules.ops.api import worker

    heard: list[tuple[str, str | None]] = []

    async def after_finish(job, status, error, entry):
        heard.append((status, error))

    monkeypatch.setattr(worker, "_after_finish", after_finish)

    def claimed(attempts: int) -> dict:
        job = {
            "_id": ObjectId(),
            "type": "match_and_price",
            "projectId": ObjectId(),
            "status": "running",
            "attempts": attempts,
            "workerId": "w",
            "claimGeneration": 1,
        }
        database["jobs"].insert_one(job)
        return job

    async def three() -> None:
        await worker.finish(claimed(1), False, "flaky", "")
        await worker.finish(claimed(worker.MAX_ATTEMPTS), False, "broken", "")
        await worker.finish(claimed(1), True, None, "", "priced")

    run(three())
    assert heard == [("dead", "broken"), ("done", None)]


def test_a_job_types_own_hook_replaces_the_default(database, monkeypatch) -> None:
    """An extract has more to do when it ends - its documents, its late uploads - and says so when it registers."""
    from bson import ObjectId

    from cbc.modules.ops.api import worker

    heard: list[str] = []

    async def default(job, status, error, entry):
        heard.append(f"default {job['type']}")

    async def own(job, status, error, entry):
        heard.append(f"own {job['type']}")

    monkeypatch.setattr(worker, "_after_finish", default)
    monkeypatch.setattr(worker, "_after", {"extract_bid_set": own})

    async def both() -> None:
        for job_type in ("extract_bid_set", "match_and_price"):
            job = {
                "_id": ObjectId(),
                "type": job_type,
                "projectId": ObjectId(),
                "status": "running",
                "attempts": 1,
                "workerId": "w",
                "claimGeneration": 1,
            }
            database["jobs"].insert_one(job)
            await worker.finish(job, True, None, "", "ok")

    run(both())
    assert heard == ["own extract_bid_set", "default match_and_price"]


def test_a_pass_over_a_bid_runs_syncs_and_finishes(database, monkeypatch, tmp_path) -> None:
    """The path every Claude job takes, with the CLI faked: the bid's saga starts, the
    pass runs in its sandbox, the slice's sync writes, and the job ends done."""
    from bson import ObjectId

    from cbc.core.claude_cli import RunResult
    from cbc.modules.ops.api import claude_pass, worker
    from cbc.modules.projects.api import pipeline
    from cbc.worker_kit import sandbox

    monkeypatch.setattr(settings, "storage_root", tmp_path / "projects")
    monkeypatch.setattr(claude_pass, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sandbox, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sandbox, "ensure_workspace_trusted", lambda workspace: True)  # never the real ~/.claude.json
    monkeypatch.setattr(sandbox, "mode", lambda: "process")
    monkeypatch.setattr(
        claude_pass.runner, "run_claude", lambda **_: RunResult(ok=True, output="ran", error=None, returncode=0)
    )

    project_id = ObjectId()
    database[names.BID_REQUESTS].insert_one(
        {"_id": project_id, "code": "CBC-PASS", "slug": "pass_smoke", "name": "Pass smoke"}
    )
    job = {
        "_id": ObjectId(),
        "type": "build_proposal",
        "projectId": project_id,
        "status": "running",
        "attempts": 1,
        "workerId": worker.WORKER_ID,
        "claimGeneration": 1,
        "payload": {},
        "createdAt": _now(),
    }
    database["jobs"].insert_one(job)
    synced: list[str] = []

    async def sync(job, project):
        synced.append(project["slug"])
        return "synced"

    run(pipeline.run_pass(job, sync=sync))

    stored = database["jobs"].find_one({"_id": job["_id"]})
    assert stored["status"] == "done", stored.get("error")
    assert stored["note"].startswith("synced")
    assert stored["recording"].startswith("projects/pass_smoke/")
    assert synced == ["pass_smoke"]
    bid = database[names.BID_REQUESTS].find_one({"_id": project_id})
    assert bid["chainState"] == "quoting" and "producedBy" in bid


def test_a_reap_that_exhausts_attempts_reaches_the_dead_letter_hook(database, monkeypatch) -> None:
    from bson import ObjectId

    from cbc.modules.ops.api import worker
    from cbc.modules.ops.features.WorkerLoop import reap_abandoned

    dead: list[str] = []

    async def on_dead(job, detail):
        dead.append(detail)

    monkeypatch.setattr(worker, "_on_dead", on_dead)
    database["jobs"].insert_one(
        {
            "type": "match_and_price",
            "projectId": ObjectId(),
            "status": "running",
            "attempts": worker.MAX_ATTEMPTS,
            "createdAt": _now(),
            "heartbeatAt": None,
        }
    )
    run(reap_abandoned())
    assert dead == ["worker stopped while this job was running"]
