"""W2d: the turn budget must reach the jobs that actually run.

`limits_for` used to grant the pipeline budget only to `run_full_pipeline`, which
is in `RETIRED_JOB_TYPES` and refused by the API - so `extract_bid_set`, a
multi-phase wave on a set that can be 744 pages, ran on the one-phase `MAX_TURNS`
and hit the ceiling. The orchestrated chain must be both runnable and budgeted.
"""
from __future__ import annotations

from cbc.modules.ops.api import claude_pass
from cbc.modules.ops.domain.jobs import RETIRED_JOB_TYPES
from cbc.modules.projects.api.autopilot import ORCHESTRATED_CHAIN


def test_the_orchestrated_chain_is_live_and_budgeted() -> None:
    for job_type in ORCHESTRATED_CHAIN:
        assert job_type not in RETIRED_JOB_TYPES, f"{job_type} is retired but chained"
        _timeout, max_turns = claude_pass.limits_for(job_type)
        assert max_turns >= claude_pass.MAX_TURNS, (
            f"{job_type} gets {max_turns} turns, below the base MAX_TURNS"
        )


def test_extraction_gets_the_pipeline_budget() -> None:
    for job_type in ("extract_bid_set", "rerun_extraction"):
        assert claude_pass.limits_for(job_type) == (
            claude_pass.PIPELINE_TIMEOUT,
            claude_pass.PIPELINE_MAX_TURNS,
        )


def test_a_plain_job_keeps_the_one_phase_budget() -> None:
    for job_type in ("match_and_price", "build_proposal", "ingest_pricebook"):
        assert claude_pass.limits_for(job_type) == (
            claude_pass.JOB_TIMEOUT,
            claude_pass.MAX_TURNS,
        )


def test_run_full_pipeline_stays_in_the_table_for_requeued_history() -> None:
    """_CLAIM_ALL_EXTRA still claims a requeued historical run_full_pipeline."""
    assert claude_pass.limits_for("run_full_pipeline") == (
        claude_pass.PIPELINE_TIMEOUT,
        claude_pass.PIPELINE_MAX_TURNS,
    )


def test_a_wave_leg_is_capped_below_the_whole_job_budget() -> None:
    assert claude_pass.WAVE_LEG_MAX_TURNS <= claude_pass.PIPELINE_MAX_TURNS
