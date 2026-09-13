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
    from cbc.core import toolsets

    ingest = prompts.build(
        {"type": "ingest_pricebook", "payload": {"filename": "hager.pdf"}}, None
    )
    assert "`pricebook` MCP server" not in ingest
    for name in ("catalog", "pdf-tools"):
        assert name in toolsets.SERVERS

