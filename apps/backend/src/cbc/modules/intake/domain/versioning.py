"""The estimate-version chain, and the state machine that moves along it.

`collections.mongodb.md` §3.26 describes `estimateVersions` as an immutable chain
- v1 -> v2 -> v3 - in which a superseded version records what replaced it and a
locked one "must never be written again".

None of that was stored. Versions were independent documents with no
`previousVersionId`, no `supersededByVersionId`, no `lockedAt`, no `status` and no
`statusHistory`; the head of the chain was whatever sorted highest by `version`,
nothing marked a version superseded, and `mark_reconciled` wrote to versions long
after they were created. FR-14 asks that an addendum be absorbed "without losing
prior work" - and a chain you cannot walk backwards is not prior work, it is a
pile.

The transition table is the specification's, copied edge for edge from §3.26. Two
of its properties matter more than the rest:

  * `pendingReview -> approved` is the only route to `approved`, and it needs a
    named human. NFR-1: no estimate is sent without explicit estimator approval,
    and the schema is where that is enforced rather than hoped for.
  * every live state can be superseded, because an addendum can arrive at any
    point in a bid - including after the proposal has gone out (Matrix 4.1).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# §3.26, in order of progress. `superseded` is terminal.
STATUSES = ("draft", "priced", "pendingReview", "approved", "sent", "superseded")

LIVE = tuple(status for status in STATUSES if status != "superseded")

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("priced", "superseded"),
    "priced": ("pendingReview", "superseded"),
    # Edits requested sends it back rather than forward.
    "pendingReview": ("draft", "approved", "superseded"),
    "approved": ("sent", "superseded"),
    "sent": ("superseded",),
    "superseded": (),
}

# Transitions a machine may not make on its own. NFR-1 is the whole reason the
# copilot drafts and does not send.
HUMAN_ONLY = frozenset({"approved"})


class VersionLocked(Exception):
    """Raised when something tries to write a version that has been sealed."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_version(
    *,
    previous: dict[str, Any] | None,
    number: int,
    reason: str,
    actor: str | None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """The fields a new link in the chain starts life with."""
    return {
        "version": number,
        "previousVersionId": (previous or {}).get("_id"),
        "supersededByVersionId": None,
        "lockedAt": None,
        "status": "draft",
        "statusHistory": [],
        "approvedBy": None,
        "approvedAt": None,
        "versionReason": reason,
        "createdAt": at or now(),
        "createdBy": actor,
    }


def supersede(
    version: dict[str, Any], *, by_id: Any, actor: str | None, at: datetime | None = None
) -> dict[str, Any]:
    """Seal a version because a newer one replaced it.

    Returns the changes to apply, so the caller can write them in whatever way it
    already writes - this module never touches the database.
    """
    moment = at or now()
    return {
        "supersededByVersionId": by_id,
        "lockedAt": moment,
        "status": "superseded",
        "statusHistory": [
            *version.get("statusHistory", []),
            transition(
                version.get("status", "draft"),
                "superseded",
                actor=actor,
                note=f"superseded by {by_id}",
                at=moment,
                # A supersede is the system following an estimator's upload, not
                # a person choosing a state, so it is exempt from HUMAN_ONLY.
                system=True,
            ),
        ],
    }


def guard_writable(version: dict[str, Any]) -> None:
    """Refuse to write a sealed version. §3.26: it must never be written again."""
    if version.get("lockedAt") is not None:
        raise VersionLocked(
            f"version {version.get('version')} was sealed at {version['lockedAt']} "
            f"(status {version.get('status')!r}); write to the version that "
            "superseded it instead"
        )


def transition(
    current: str,
    target: str,
    *,
    actor: str | None,
    note: str | None = None,
    at: datetime | None = None,
    system: bool = False,
) -> dict[str, Any]:
    """One `statusHistory` entry, refusing any edge the specification omits."""
    if target not in TRANSITIONS.get(current, ()):
        allowed = ", ".join(TRANSITIONS.get(current, ())) or "nothing"
        raise ValueError(
            f"{current} -> {target} is not a transition in §3.26; "
            f"{current} may go to: {allowed}"
        )
    if target in HUMAN_ONLY and not system and not actor:
        raise ValueError(
            f"{target!r} needs a named person (NFR-1): no estimate is approved "
            "without explicit estimator approval"
        )
    return {"from": current, "to": target, "at": at or now(), "by": actor, "note": note}


def head(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one nothing supersedes.

    The specification indexes `supersededByVersionId: null` for exactly this,
    rather than sorting by version number and hoping.
    """
    open_versions = [v for v in versions if v.get("supersededByVersionId") is None]
    if not open_versions:
        return None
    return max(open_versions, key=lambda v: v.get("version", 0))
