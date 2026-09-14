"""Autopilot: one session carries a bid from upload to draft.

The gated flow is the default and is unchanged. What is tested here is the choice
made at upload, the budget a six-phase run gets, the progress a long run reports
while it works, and the guarantee that survives all of it: nothing is sent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.shared import FIXTURE_PDF, FIXTURES, ROOT, mongo_client


# â”€â”€ the choice made at upload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_the_pipeline_job_is_exclusive_per_bid() -> None:
    """A second drawing on a running bid is more files, not a second run."""
    from cbc.modules.ops.domain.jobs import EXCLUSIVE_JOB_TYPES
    from cbc.modules.ops.api.jobs import EXCLUSIVE

    assert "run_full_pipeline" in EXCLUSIVE_JOB_TYPES
    assert "run_full_pipeline" in EXCLUSIVE


def test_the_pipeline_job_type_is_a_known_job_type() -> None:
    from typing import get_args

    from cbc.modules.ops.domain.jobs import JobType

    assert "run_full_pipeline" in get_args(JobType)


# â”€â”€ the budget a six-phase run gets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_full_run_gets_a_bigger_budget_than_one_phase() -> None:
    """60 turns and an hour are sized for one phase; this is nine subagents."""
    from cbc.modules.ops.api.claude_pass import JOB_TIMEOUT, MAX_TURNS, limits_for

    timeout, turns = limits_for("run_full_pipeline")
    assert timeout > JOB_TIMEOUT and turns > MAX_TURNS
    assert limits_for("extract_bid_set") == (JOB_TIMEOUT, MAX_TURNS), "gated path unchanged"


def test_a_full_run_gets_every_mcp_server() -> None:
    """It reads drawings, prices lines and writes artifacts in one pass."""
    from cbc.modules.ops.api import toolsets

    servers = set(json.loads(toolsets.config_for("run_full_pipeline"))["mcpServers"])
    assert servers == set(toolsets.SERVERS)
    # And the per-phase scoping that makes a single phase cheap is untouched:
    # drawings, the artifact store, and the reference data a take-off needs for
    # finishes / frame depths / FRP constants. No pricing tools.
    reading = set(json.loads(toolsets.config_for("extract_bid_set"))["mcpServers"])
    assert reading == {"pdf-tools", "artifact-storage", "reference", "bid-docs"}
    assert not reading & {"catalog", "calc-engine", "p21-connector"}


# â”€â”€ the prompt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_the_prompt_delegates_to_every_phase_subagent() -> None:
    """A phase with no subagent named is a phase that will not run."""
    from cbc.worker_kit import prompts

    prompt = prompts.pipeline_for("projects/demo", code="CBC-260001")
    for subagent in (
        "intake-coordinator", "spec-scope-analyst", "takeoff-engineer",
        "frp-specialist", "product-matcher", "pricing-engineer",
        "quality-reviewer", "delivery-agent",
    ):
        assert subagent in prompt, f"{subagent} is never invoked"
        assert (ROOT / ".claude" / "agents" / f"{subagent}.md").exists()
    assert "quote-builder" not in prompt


def test_the_prompt_halts_without_sending(the_prompt=None) -> None:
    """NFR-1 does not soften because nobody is watching."""
    from cbc.worker_kit import prompts

    prompt = prompts.pipeline_for("projects/demo")
    assert "Draft ready for estimator review" in prompt
    assert "delivery-agent" in prompt
    assert "Do NOT send anything" in prompt, "the shared preamble is missing"


def test_the_prompt_waits_for_subagents_before_duplicating_work() -> None:
    from cbc.worker_kit import prompts

    prompt = prompts.pipeline_for("projects/demo")
    assert "Wait for each subagent to finish" in prompt
    assert "Never duplicate a subagent's work" in prompt
    assert "one subagent at a time" in prompt.lower()


def test_build_proposal_only_delivery_agent_halts() -> None:
    from cbc.worker_kit import prompts

    build = prompts.build({"type": "build_proposal", "payload": {}}, {"slug": "demo", "code": "DB-001"})
    assert "Only the **delivery-agent** reports the final halt message" in build
    assert "quote-builder" not in build
    assert "do not write html" in build.lower()


def test_match_prompt_forbids_ives_list_multiplier() -> None:
    from cbc.worker_kit import prompts

    match = prompts.build(
        {"type": "match_and_price", "payload": {}},
        {"slug": "demo", "code": "DB-001"},
    )
    assert "IVES" in match
    assert "MANUAL" in match
    assert "LIST_X_MULTIPLIER" in match


def test_the_prompt_carries_the_shared_constraints() -> None:
    """One source for the rules, whichever entry point starts the run."""
    from cbc.worker_kit import prompts

    assert prompts.preamble_for("projects/demo") in prompts.pipeline_for("projects/demo")


def test_the_prompt_says_to_resume_rather_than_reread() -> None:
    """Three attempts on a 744-page set must not read it three times."""
    from cbc.worker_kit import prompts

    prompt = prompts.pipeline_for("projects/demo").lower()
    assert "resume" in prompt and "already exists" in prompt


def test_the_prompt_refuses_to_guess_a_flagged_line() -> None:
    """NFR-2, and on this path the review at the end is the only review."""
    from cbc.worker_kit import prompts

    prompt = prompts.pipeline_for("projects/demo")
    assert "do not guess" in prompt.lower()
    assert "MANUAL" in prompt


def test_the_shell_entry_point_uses_the_same_prompt() -> None:
    """It used to carry a third hand-copy of the rules."""
    script = (ROOT / "workflows" / "run_full_pipeline.sh").read_text(encoding="utf-8")
    # The flags are assembled into PROMPT_ARGS now, so that --solo can be added
    # for a provider that cannot delegate. The point is unchanged: the prompt is
    # asked for, never restated.
    assert "cbc.worker_kit.prompts" in script
    assert "--pipeline" in script
    assert "Respect every rule" not in script, "the rules are restated again"


# â”€â”€ progress while it runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_the_board_advances_as_each_phase_lands(tmp_path: Path) -> None:
    """`stage` is only written when a job ends, and this job can run for an hour."""
    from cbc.modules.extraction.api.passes import phase_reached

    assert phase_reached(tmp_path) is None, "nothing written yet"

    def write(relative: str) -> None:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    for relative, expected_stage, expected_progress, expected_label in [
        ("extracted/scope_metadata.json", "intake", 10, "Intake"),
        ("extracted/scope_summary.json", "extraction", 25, "Spec scoping"),
        ("extracted/door_schedule.json", "extraction", 40, "Take-off"),
        ("extracted/hardware_sets.json", "quote", 55, "Product matching"),
        ("priced/line_items.json", "quote", 70, "Pricing"),
        ("quotation.html", "proposal", 85, "Quote built"),
        ("review/review_summary.html", "proposal", 95, "Review"),
    ]:
        write(relative)
        assert phase_reached(tmp_path) == (expected_stage, expected_progress, expected_label)


def test_progress_only_ever_moves_forward(tmp_path: Path) -> None:
    """Phases are reported furthest-first, so an early file cannot pull it back."""
    from cbc.modules.extraction.api.passes import phase_reached

    for relative in ("quotation.html", "extracted/scope_metadata.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    stage, progress, _ = phase_reached(tmp_path)
    assert (stage, progress) == ("proposal", 85)


# â”€â”€ against a real database â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


TEST_DB = "cbc_opshub_test_autopilot"
FIXTURE = FIXTURE_PDF


@pytest.fixture(scope="module")
def client():
    from tests.shared import opshub_client

    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


# A second upload of the same bytes is a duplicate, whatever it is called, and
# the API short-circuits it. An addendum needs a genuinely different file.
ADDENDUM_FIXTURE = (
    FIXTURES / "pdfs"
    / "Shakopee,_MN,_#0131_-_Reimage_Final_Drawings_-_6.12.26_pdf.pdf"
)


def _upload(client, code: str, name: str = "plans.pdf", kind: str = "plan"):
    source = ADDENDUM_FIXTURE if kind == "addendum" else FIXTURE
    if not source.exists():
        pytest.skip(f"fixture not present: {source}")
    with source.open("rb") as handle:
        return client.post(
            f"/api/projects/{code}/documents",
            files={"file": (name, handle, "application/pdf")},
            data={"kind": kind},
        )


def _bid(client, *, autopilot: bool) -> str:
    created = client.post(
        "/api/projects",
        json={"name": f"Autopilot {autopilot} bid", "state": "OH", "autopilot": autopilot},
    )
    assert created.status_code == 201, created.text
    assert created.json()["autopilot"] is autopilot
    return created.json()["code"]


def test_a_normal_bid_still_stops_for_the_estimator(client) -> None:
    """The gated flow is the default and must not change."""
    code = _bid(client, autopilot=False)
    body = _upload(client, code).json()

    assert body["job"]["type"] == "extract_bid_set"
    assert body["autopilot"] is False


def test_an_autopilot_bid_runs_the_whole_pipeline(client) -> None:
    """`run_full_pipeline` is retired. Autopilot now starts the domain chain at
    extract_bid_set and each worker enqueues the next phase, so what marks a run
    as "the whole pipeline" is payload.orchestrate, not the job type."""
    code = _bid(client, autopilot=True)
    body = _upload(client, code).json()

    assert body["job"]["type"] == "extract_bid_set"
    assert body["job"]["payload"]["orchestrate"] is True
    assert body["autopilot"] is True


def test_an_addendum_is_never_autopiloted(client) -> None:
    """An addendum is a diff against prior work, not a fresh bid (Matrix 4.1)."""
    code = _bid(client, autopilot=True)
    _upload(client, code)
    body = _upload(client, code, name="addendum1.pdf", kind="addendum").json()

    assert body["job"]["type"] == "ingest_addendum"
    assert "orchestrate" not in (body["job"].get("payload") or {})
    assert body["autopilot"] is False


def test_several_drawings_become_one_run(client) -> None:
    """A run reads the whole of uploads/raw/; starting on the first file would
    silently leave the other two out of the bid."""
    code = _bid(client, autopilot=True)
    jobs = [_upload(client, code, name=f"sheet{n}.pdf").json()["job"] for n in range(3)]

    assert len({job["id"] for job in jobs}) == 1, "one bid set, one pipeline"
    assert jobs[0]["nextAttemptAt"], "the run does not wait for the rest of the set"


def test_the_installation_default_applies_when_the_bid_says_nothing(client) -> None:
    from pymongo import MongoClient

    from cbc.shared.config import settings

    raw = mongo_client(serverSelectionTimeoutMS=5000)
    try:
        raw[TEST_DB]["settings"].update_one(
            {"_id": "pipeline"}, {"$set": {"autopilotDefault": True}}, upsert=True
        )
        created = client.post("/api/projects", json={"name": "Inherits the default"})
        assert created.json()["autopilot"] is True

        # A bid that says so explicitly still wins.
        explicit = client.post(
            "/api/projects", json={"name": "Says otherwise", "autopilot": False}
        )
        assert explicit.json()["autopilot"] is False
    finally:
        raw[TEST_DB]["settings"].delete_one({"_id": "pipeline"})
        raw.close()


def test_autopilot_can_be_turned_off_on_an_existing_bid(client) -> None:
    code = _bid(client, autopilot=True)
    assert client.patch(f"/api/projects/{code}", json={"autopilot": False}).json()[
        "autopilot"
    ] is False
    assert _upload(client, code).json()["job"]["type"] == "extract_bid_set"

