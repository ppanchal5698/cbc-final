"""What other modules may record on a bid, and what a bid announces."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.projects.infrastructure.collections import bid_requests

# Published with project_id= while a bid is being deleted - after its jobs are
# cancelled, before its record goes - so each module removes its own rows.
PROJECT_DELETED = "projects.project_deleted"
# Published with project= and prior= when a bid starts from a prior one (FR-11),
# before the bid records it, so quoting can refuse and nothing is half-done.
TEMPLATE_CHOSEN = "projects.template_chosen"


async def set_version(project_id: Any, number: int) -> None:
    """The bid's current version, after an addendum snapshot."""
    await bid_requests().update_one({"_id": project_id}, {"$set": {"version": number}})


async def add_alternate(project_id: Any, name: str) -> None:
    """Name a new alternate group on the bid."""
    await bid_requests().update_one(
        {"_id": project_id},
        {"$addToSet": {"alternates": name}, "$set": {"updatedAt": datetime.now(timezone.utc)}},
    )


async def describe_alternate(project_id: Any, spec: dict[str, Any]) -> None:
    """What an alternate is - its kind, its place on the bid form, what it says
    (FR-14) - kept beside its name, one entry per name."""
    now = datetime.now(timezone.utc)
    found = await bid_requests().update_one(
        {"_id": project_id, "alternateSpecs.name": spec["name"]},
        {"$set": {"alternateSpecs.$": spec, "updatedAt": now}},
    )
    if not found.matched_count:
        await bid_requests().update_one(
            {"_id": project_id}, {"$push": {"alternateSpecs": spec}, "$set": {"updatedAt": now}}
        )


class AddendumExists(ValueError):
    """An addendum by that number is already in the bid's log."""


async def log_addendum(project_id: Any, entry: dict[str, Any], *, by: str | None = None) -> dict[str, Any]:
    """Add an addendum to the bid's log (FR-14) - the next number when none is
    given - and return it as stored. An addendum PDF uploaded to the bid is
    logged by intake; one announced by phone or email, by the estimator."""
    project = await bid_requests().find_one({"_id": project_id}, {"addenda": 1}) or {}
    numbers = [a.get("number") for a in project.get("addenda") or []]
    number = entry.get("number") or max([n for n in numbers if isinstance(n, int)] or [0]) + 1
    if number in numbers:
        raise AddendumExists(f"addendum {number} is already logged on this bid")
    now = datetime.now(timezone.utc)
    stored = {**{k: v for k, v in entry.items() if v is not None}, "number": number,
              "recordedAt": now, "recordedBy": by}
    await bid_requests().update_one(
        {"_id": project_id}, {"$push": {"addenda": stored}, "$set": {"updatedAt": now}}
    )
    return stored


async def remember_removed(project_id: Any, keys: list[str]) -> None:
    """Openings the estimator deleted, by the key a take-off reaches them by, so
    the next take-off of the same sheets leaves them out rather than back in."""
    if keys:
        await bid_requests().update_one(
            {"_id": project_id}, {"$addToSet": {"removedOpenings": {"$each": keys}}}
        )


async def record_hand_off(project_id: Any, recipient: str | None) -> None:
    """The estimator signed the proposal off and routed it to `recipient`."""
    now = datetime.now(timezone.utc)
    await bid_requests().update_one(
        {"_id": project_id},
        {"$set": {"handedOffTo": recipient, "handedOffAt": now, "updatedAt": now}},
    )


async def note_phase(project_id: Any, phase: str, note: str) -> None:
    """Where the pipeline stands, in words: the bid's `phase` and the `pipelineNote` under it."""
    await bid_requests().update_one(
        {"_id": project_id},
        {"$set": {"phase": phase, "pipelineNote": note, "updatedAt": datetime.now(timezone.utc)}},
    )


async def set_stage(project_id: Any, stage: str, progress: int, *, phase: str | None = None) -> None:
    """How far along the board shows the bid - and the phase it has reached, when known."""
    fields: dict[str, Any] = {"stage": stage, "progress": progress}
    if phase is not None:
        fields["phase"] = phase
    fields["updatedAt"] = datetime.now(timezone.utc)
    await bid_requests().update_one({"_id": project_id}, {"$set": fields})
