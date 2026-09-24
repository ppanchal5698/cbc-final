"""The two ways to start a run must operate under the same rules and tools.

`_phase.sh` and `run_full_pipeline.sh` already share the preamble with the worker.
They did not share the tool scope: both spawned the CLI with no `--mcp-config`,
no `--strict-mcp-config` and no `--disallowed-tools`, so a headless take-off
carried every server in `.mcp.json` plus WebSearch and WebFetch - a wider surface
than the identical phase gets through the Ops-Hub, on the path with nobody
watching it.

`_phase.sh` also hardcoded "Delegate to the `${agent}` subagent", so a provider
that cannot call the Agent tool was told to use it anyway.
"""
from __future__ import annotations

import re

import pytest

from cbc.modules.ops.api import toolsets
from cbc.modules.pricing.api import preprice
from tests.shared import PKG, ROOT

WORKFLOWS = ROOT / "workflows"
PHASE_SH = (WORKFLOWS / "_phase.sh").read_text(encoding="utf-8")
PIPELINE_SH = (WORKFLOWS / "run_full_pipeline.sh").read_text(encoding="utf-8")
SPAWNING_SCRIPTS = {"_phase.sh": PHASE_SH, "run_full_pipeline.sh": PIPELINE_SH}


def _mapped_agents() -> dict[str, str]:
    """Parse the agent -> job type table out of the shell case statement."""
    block = re.search(r"job_type_for\(\) \{(.+?)\n\}", PHASE_SH, re.DOTALL)
    assert block, "job_type_for is gone from _phase.sh"
    mapping: dict[str, str] = {}
    for names, job_type in re.findall(
        r"^\s*([a-z0-9|-]+)\)\s*\n?\s*echo \"([a-z_]+)\"", block.group(1), re.MULTILINE
    ):
        for name in names.split("|"):
            mapping[name] = job_type
    return mapping


@pytest.mark.parametrize("name", sorted(SPAWNING_SCRIPTS))
def test_a_headless_run_is_scoped_like_a_worker_run(name: str) -> None:
    body = SPAWNING_SCRIPTS[name]
    assert "cbc.modules.ops.api.toolsets" in body, f"{name} builds its own scope"
    spawn = re.search(r'"\$\{CLAUDE_BIN\}"[^\n]*', body)
    assert spawn, f"{name} no longer spawns the CLI"
    assert "SCOPE" in spawn.group(0) or "scope" in spawn.group(0), (
        f"{name} spawns the CLI without the tool scope: {spawn.group(0)}"
    )


def test_every_agent_has_a_job_type() -> None:
    """An unmapped agent used to mean the full tool surface. Now it is an error,
    but only if every agent is actually in the table."""
    mapping = _mapped_agents()
    on_disk = {p.stem for p in (ROOT / ".claude" / "agents").glob("*.md")}
    assert not on_disk - set(mapping), f"agents with no tool scope: {on_disk - set(mapping)}"


def test_every_mapped_job_type_is_a_real_profile() -> None:
    """A typo here would scope a phase to `PROFILES.get(...) or list(SERVERS)`,
    which is silently everything."""
    for agent, job_type in _mapped_agents().items():
        assert job_type in toolsets.PROFILES, f"{agent} -> unknown job type {job_type!r}"


def test_the_reading_phases_get_no_pricing_tools() -> None:
    """The scope the mapping actually produces, not just that it produces one."""
    import json

    mapping = _mapped_agents()
    servers = json.loads(toolsets.config_for(mapping["takeoff-engineer"]))["mcpServers"]
    assert "p21-connector" not in servers
    assert "calc-engine" not in servers
    assert "pdf-tools" in servers


@pytest.mark.parametrize("name", sorted(SPAWNING_SCRIPTS))
def test_a_solo_provider_is_not_told_to_delegate(name: str) -> None:
    body = SPAWNING_SCRIPTS[name]
    assert "CBC_SOLO" in body, f"{name} assumes every provider can delegate"
    assert "--solo" in body, f"{name} never asks prompts.py for the solo preamble"


@pytest.mark.parametrize("name", sorted(SPAWNING_SCRIPTS))
def test_the_scope_guard_cannot_fail_open(name: str) -> None:
    """Scoping the run is only a guard if failing to scope it stops the run.

    `mapfile -t scope < <(python -m cbc.modules.ops.api.toolsets ...)` reports mapfile's own
    status, never the command's, and `set -euo pipefail` does not cover process
    substitution. A failed toolsets call therefore left `scope` empty and the CLI
    was spawned with no --strict-mcp-config and no --disallowed-tools, under
    --dangerously-skip-permissions: every server in .mcp.json plus WebSearch and
    WebFetch, which is exactly what the lines above it exist to prevent.
    """
    # Code only. The note explaining this bug names the broken form.
    source = SPAWNING_SCRIPTS[name].splitlines()
    body = "\n".join(line for line in source if not line.lstrip().startswith("#"))

    assert "mapfile" in body, f"{name} no longer reads a scope at all"
    assert not re.search(r"mapfile[^\n]*<\s*<\(", body), (
        f"{name} reads the tool scope through process substitution, whose exit "
        "status mapfile discards - the guard falls open to an unrestricted run"
    )
    assert re.search(r"\$\{#\w*[Ss][Cc][Oo][Pp][Ee]\[@\]\}", body), (
        f"{name} does not check that the scope it got is non-empty"
    )


@pytest.mark.parametrize(
    "name,turns",
    [("_phase.sh", '"${CBC_MAX_TURNS:-60}"'), ("run_full_pipeline.sh", "200")],
)
def test_headless_spawn_sets_max_turns(name: str, turns: str) -> None:
    spawn = re.search(r'"\$\{CLAUDE_BIN\}"[^\n]*', SPAWNING_SCRIPTS[name])
    assert spawn, f"{name} no longer spawns the CLI"
    assert f"--max-turns {turns}" in spawn.group(0), spawn.group(0)


def test_phase_sh_requests_the_job_template() -> None:
    assert "--job-type" in PHASE_SH
    assert "cbc.worker_kit.prompts" in PHASE_SH


def test_job_type_cli_prints_extract_and_match_bodies() -> None:
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(PKG.parent)])}
    extract = subprocess.run(
        [
            sys.executable,
            "-m",
            "cbc.worker_kit.prompts",
            "--job-type",
            "extract_bid_set",
            "projects/demo",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "_sheetmap.json" in extract.stdout or "find_sheets" in extract.stdout
    match = subprocess.run(
        [
            sys.executable,
            "-m",
            "cbc.worker_kit.prompts",
            "--job-type",
            "match_and_price",
            "projects/demo",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    # The cost ladder the CLI prints follows PREPRICE_SEED, exactly as the worker's
    # does - `test_prompts.test_the_flag_selects_the_cost_ladder` pins the switch
    # itself; this asserts the headless path honours it rather than a fixed body.
    # Asserting `find_pages` unconditionally encoded the pre-seed prompt and broke
    # the moment the seed shipped on by default.
    if preprice.preprice_seed_enabled():
        assert "ran the deterministic" in match.stdout
        assert "find_pages" not in match.stdout
    else:
        assert "find_pages" in match.stdout


