"""Every prompt a job can be given must be coherent on both providers.

Two failures live here. The first: `PREAMBLE` told every run "do not `cat` your
own instructions - agents are subagent types you invoke", while `HOW_SOLO` told a
non-delegating run "read the agent definition before each phase, and follow it".
A solo run received both and had to pick. The second: `RERUN` interpolated the
delegated how-block, which ends on a colon introducing a phase list, and then
listed no phases - so a re-extraction was asked to delegate to nobody, and named
neither an agent nor an output file.

Neither shows up in a unit test of the functions involved; both only exist in the
rendered text, which is what these assert.
"""
from __future__ import annotations

import typing

import pytest

from cbc.worker_kit import prompts

PROJECT = {"slug": "dutch_bros", "code": "DB-001"}
# ingest_pricebook takes payload keys instead of a project, so it renders separately.
PROJECT_JOB_TYPES = [t for t in prompts.TEMPLATES if t != "ingest_pricebook"]


def _render(job_type: str, *, delegates: bool) -> str:
    return prompts.build({"type": job_type, "payload": {}}, PROJECT, delegates=delegates)


@pytest.mark.parametrize("job_type", PROJECT_JOB_TYPES)
def test_a_solo_run_is_told_to_read_the_agent_files(job_type: str) -> None:
    """On this path nothing loads them, so reading them is the only way to get them."""
    text = _render(job_type, delegates=False)
    assert "Do read the agent files" in text
    assert "Do not `cat` the agent files" not in text


@pytest.mark.parametrize("job_type", PROJECT_JOB_TYPES)
def test_a_delegated_run_is_told_not_to(job_type: str) -> None:
    """Here each subagent loads its own definition, so reading it first buys nothing."""
    text = _render(job_type, delegates=True)
    assert "Do not `cat` the agent files" in text
    assert "Do read the agent files" not in text


@pytest.mark.parametrize("job_type", PROJECT_JOB_TYPES)
@pytest.mark.parametrize("delegates", [True, False])
def test_no_phase_list_is_introduced_and_then_omitted(
    job_type: str, delegates: bool
) -> None:
    """A how-block ends on a colon. Something has to follow it."""
    lines = [line.rstrip() for line in _render(job_type, delegates=delegates).splitlines()]
    for i, line in enumerate(lines):
        if not line.endswith(":"):
            continue
        rest = [l for l in lines[i + 1:] if l.strip()]
        assert rest, f"{job_type}: line {i + 1} introduces nothing: {line!r}"


@pytest.mark.parametrize("delegates", [True, False])
def test_a_rerun_names_its_agent_and_its_output(delegates: bool) -> None:
    """It reruns the take-off, so it must say so and say where the answer goes."""
    text = _render("rerun_extraction", delegates=delegates)
    assert "takeoff-engineer" in text
    assert "extracted/door_schedule.json" in text


def test_every_job_type_renders_on_both_providers() -> None:
    """Including ingest_pricebook, which takes a payload rather than a project."""
    for job_type in PROJECT_JOB_TYPES:
        for delegates in (True, False):
            assert _render(job_type, delegates=delegates).strip()
    ingest = prompts.build(
        {"type": "ingest_pricebook", "payload": {"filename": "hager.pdf"}}, None
    )
    assert "hager.pdf" in ingest


def test_no_prompt_names_a_server_that_does_not_exist() -> None:
    """`pricebook` was an alias over `catalog` and has been gone for some time.

    The ingest prompt still sent a run to it, so the one job whose entire purpose
    is reading a vendor sheet was told to use a server that would never connect.
    """
    from cbc.modules.ops.api import toolsets

    ingest = prompts.build(
        {"type": "ingest_pricebook", "payload": {"filename": "hager.pdf"}}, None
    )
    assert "`pricebook` MCP server" not in ingest
    for name in ("catalog", "pdf-tools"):
        assert name in toolsets.SERVERS


def test_extract_prompt_points_at_the_seeded_artifact_and_the_patch_path() -> None:
    text = _render("extract_bid_set", delegates=True)
    assert "door_schedule.json" in text
    assert "propose_patch" in text
    assert "Verify on disk" in text or "get_artifact" in text
    assert "parse_schedule" in text


def test_the_prompt_no_longer_carries_json_shape_instructions() -> None:
    """Every one of these was added after a run deviated a new way.

    `page_size must be {width,height}`, `Thickness -> notes`, `max 2
    schema-repair retries` - a list of scars on a stochastic thing, which is a
    loop that cannot converge. They are normaliser and schema concerns now, and
    a patch that breaks the contract is refused on its own.
    """
    rule = prompts.DELEGATION_RULE
    for scar in ("page_size must be", "never a thickness key",
                 "Max 2 schema-repair", "schema-repair retries",
                 "closed-world: allowlisted"):
        assert scar not in rule, f"{scar!r} is back in DELEGATION_RULE"


def test_delegation_rule_briefs_a_verifier_not_an_author() -> None:
    rule = prompts.DELEGATION_RULE
    assert "Subagent brief template" in rule
    assert "Verify on disk" in rule
    assert "propose_patch" in rule
    # The point of the whole redesign: Python owns the artifact.
    assert "already seeded" in rule or "already exists" in rule
    assert "source_page" in rule and "excerpt" in rule


def test_split_phase_handoff_and_delivery_gate_are_in_prompt() -> None:
    job = {
        "type": "build_proposal",
        "phaseState": {"pricing": {"passed": True, "artifacts": {"priced/line_items.json": "sha"}}},
    }
    text = prompts.build(job, PROJECT)
    assert "Validated handoff from earlier jobs" in text
    assert "pricing: priced/line_items.json" in text
    assert "--check-delivery" in text
    assert "do not infer estimator approval" in text
    assert "new scratch path is isolation, not a blank bid" in text
    assert "do not independently read or process" in text

    forced = prompts.build({**job, "payload": {"force": True}}, PROJECT)
    assert "Validated handoff from earlier jobs" not in forced



@pytest.mark.parametrize("job_type", PROJECT_JOB_TYPES)
def test_a_forced_job_is_told_so_whatever_its_template(job_type: str) -> None:
    """`force` used to be a string replacement that matched one template in seven.

    It swapped out "Ignore this only if told to force a clean run.", and that
    sentence lives only in the full-pipeline template. `str.replace` with no
    match is a silent no-op, so a forced `match_and_price` resumed off the very
    files it was told to distrust, made five tool calls, reported "already
    complete", and cost half a dollar. A prefix cannot miss.
    """
    forced = prompts.build({"type": job_type, "payload": {"force": True}}, PROJECT)
    assert "FORCED CLEAN RUN" in forced, job_type


@pytest.mark.parametrize("job_type", PROJECT_JOB_TYPES)
def test_an_ordinary_job_is_not_told_to_rebuild_everything(job_type: str) -> None:
    """Resume is the default, and it is the expensive thing to get wrong."""
    ordinary = prompts.build({"type": job_type, "payload": {}}, PROJECT)
    assert "FORCED CLEAN RUN" not in ordinary, job_type
