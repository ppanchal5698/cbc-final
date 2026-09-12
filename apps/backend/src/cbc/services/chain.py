"""Autopilot saga state on the project document.

`chainState` is the single source of truth for "what stage is this bid at, and
what is blocking it". `phase` and `pipelineNote` are human copy derived from it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from cbc.db import db

ChainState = Literal[
    "idle",
    "extracting",
    "extraction_done",
    "extraction_needs_review",
    "pricing",
    "pricing_failed",
    "quoting",
    "quoting_failed",
    "complete",
    "awaiting_manual_retry",
    "dead",
]

# Job type -> state written when the worker starts running it.
START_STATE: dict[str, ChainState] = {
    "extract_bid_set": "extracting",
    "rerun_extraction": "extracting",
    "run_full_pipeline": "extracting",
    "match_and_price": "pricing",
    "build_proposal": "quoting",
}

# Successful job type -> state that must be set before maybe_continue_chain.
SUCCESS_STATE: dict[str, ChainState] = {
    "extract_bid_set": "extraction_done",
    "rerun_extraction": "extraction_done",
    "run_full_pipeline": "complete",
    "match_and_price": "pricing",
    "build_proposal": "complete",
}

# maybe_continue_chain may enqueue the next domain job only from these states.
ADVANCE_FROM: dict[str, frozenset[str]] = {
    "extract_bid_set": frozenset({"extraction_done"}),
    "rerun_extraction": frozenset({"extraction_done"}),
    "match_and_price": frozenset({"pricing"}),
}

# Permanent failure of this job type -> compensating chainState.
FAIL_STATE: dict[str, ChainState] = {
    "extract_bid_set": "awaiting_manual_retry",
    "rerun_extraction": "awaiting_manual_retry",
    "run_full_pipeline": "awaiting_manual_retry",
    "match_and_price": "pricing_failed",
    "build_proposal": "quoting_failed",
}

_COPY: dict[ChainState, tuple[str, str]] = {
    "idle": ("Idle", ""),
    "extracting": ("Extracting", "Claude is reading the bid set."),
    "extraction_done": ("Take-off complete", ""),
    "extraction_needs_review": (
        "Needs review",
        "Extraction needs an estimator check before pricing can start.",
    ),
    "pricing": ("Pricing", "Matching products and applying the price book."),
    "pricing_failed": (
        "Pricing failed",
        "Pricing stopped. Extraction is intact — review and re-run pricing.",
    ),
    "quoting": ("Building proposal", "Rendering the quotation and review pack."),
    "quoting_failed": (
        "Proposal failed",
        "Quote lines are intact — review and re-run the proposal.",
    ),
    "complete": ("Draft ready", ""),
    "awaiting_manual_retry": (
        "Needs attention",
        "The last run failed. Retry from the dead-letter queue or re-run the step.",
    ),
    "dead": (
        "Needs attention",
        "This bid's last job is dead-lettered. Retry from the ops queue.",
    ),
}

# Permanent pricing/quoting failure turns autopilot off so the chain does not
# silently halt in an ambiguous "still automatic" state.
DISABLE_AUTOPILOT: frozenset[str] = frozenset(
    {"pricing_failed", "quoting_failed", "awaiting_manual_retry", "dead"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def copy_for(state: ChainState) -> tuple[str, str]:
    return _COPY.get(state, (state.replace("_", " ").title(), ""))


async def set_state(
    project_id: Any,
    state: ChainState,
    *,
    detail: str | None = None,
) -> None:
    """Write chainState and the derived human fields."""
    if project_id is None:
        return
    phase, note = copy_for(state)
    if detail:
        note = detail if not note else f"{note} {detail}".strip()
    update: dict[str, Any] = {
        "chainState": state,
        "phase": phase,
        "updatedAt": _now(),
    }
    if note:
        update["pipelineNote"] = note
    else:
        # Clear leftover notes when the bid is healthy again.
        pass
    sets: dict[str, Any] = {"$set": update}
    if not note:
        sets["$unset"] = {"pipelineNote": ""}
    if state in DISABLE_AUTOPILOT:
        update["autopilot"] = False
    await db.projects.update_one({"_id": project_id}, sets)


def can_advance(job_type: str, chain_state: str | None) -> bool:
    """Whether autopilot may enqueue the next domain job after this success."""
    allowed = ADVANCE_FROM.get(job_type)
    if allowed is None:
        return False
    return chain_state in allowed
