"""Matching an opening to a catalog item, decided in code.

FR-4: *match each extracted opening to the closest library entry - respecting
rating, handing, and finish.* That requirement had no implementation. It lived in
prompt text (`match-hardware-sets/SKILL.md`, `product-matcher.md`) and nothing
enforced it, so the only thing standing between a rated opening and an unrated
match was an instruction to a language model.

Matrix 7.3 does not treat that as a preference: *"an unrated match on a rated
opening is a defect"*. A defect is not something you ask a model nicely to avoid.

So rating, handing and finish are **hard filters** here. A candidate that fails
one is not ranked lower - it is excluded, and the reason is recorded in
`failedOn` so an estimator can see what was rejected and why. What is left is
ranked, and the model's job shrinks to choosing among candidates that are all
already legal - the same shape as the deterministic pre-take-off.

The scoring is deliberately dull. This is not trying to be clever about which
of three legal hinges is best; it is making sure the illegal ones never reach the
question. Estimating judgment is the estimator's (NFR-2 - "here are 3 close
matches" is the target behaviour, not a single confident answer).
"""
from __future__ import annotations

from typing import Any, Iterable

from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR

# How many candidates to surface. The reference rule describes an estimator
# asking "here are 3 close matches - is it one of these?", and that is the
# behaviour being reproduced.
TOP_N = 3


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _rating_minutes(value: Any) -> int | None:
    """`90`, `"90"`, `"90 min"`, `"90-minute"` -> 90. Anything else -> None."""
    text = _norm(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def rating_conflict(opening_rating: Any, candidate_rating: Any) -> bool:
    """True when a rated opening would be given an item that cannot carry it.

    An unrated opening takes anything. A rated opening needs an item rated *at
    least* as high - a 90-minute opening may take a 90-minute leaf, never a
    45-minute one. Matrix 7.3.
    """
    needed = _rating_minutes(opening_rating)
    if needed is None:
        return False
    offered = _rating_minutes(candidate_rating)
    return offered is None or offered < needed


def _handing_conflict(opening: Any, candidate: Any) -> bool:
    """Handed hardware must match the opening. Unhanded items say nothing."""
    wanted, offered = _norm(opening), _norm(candidate)
    if wanted is None or offered is None:
        return False  # nothing claimed, nothing to contradict
    if offered in {"NON-HANDED", "NONHANDED", "REVERSIBLE", "ANY"}:
        return False
    return wanted != offered


def _finish_conflict(opening: Any, candidate: Any, *, equivalent) -> bool:
    """US26D and 626 are the same finish (NR-3); US19 and 26D are not."""
    wanted, offered = _norm(opening), _norm(candidate)
    if wanted is None or offered is None:
        return False
    return not equivalent(wanted, offered)


def _same_finish(left: str, right: str) -> bool:
    return left == right


def evaluate(
    opening: dict[str, Any],
    candidate: dict[str, Any],
    *,
    finish_equivalent=_same_finish,
) -> dict[str, Any]:
    """One candidate, judged. `failedOn` non-empty means it is not a candidate.

    Returned rather than raised, because an estimator reviewing a flagged line
    wants to see what was rejected and why - a silently shorter list teaches
    nobody anything (NFR-2).
    """
    matched: list[str] = []
    failed: list[str] = []

    if rating_conflict(opening.get("fire_rating"), candidate.get("fire_rating")):
        failed.append("fire_rating")
    elif _rating_minutes(opening.get("fire_rating")) is not None:
        matched.append("fire_rating")

    if _handing_conflict(opening.get("handing"), candidate.get("handing")):
        failed.append("handing")
    elif _norm(opening.get("handing")) and _norm(candidate.get("handing")):
        matched.append("handing")

    if _finish_conflict(
        opening.get("finish"), candidate.get("finish"), equivalent=finish_equivalent
    ):
        failed.append("finish")
    elif _norm(opening.get("finish")) and _norm(candidate.get("finish")):
        matched.append("finish")

    for soft in ("series", "manufacturer", "door_type"):
        wanted, offered = _norm(opening.get(soft)), _norm(candidate.get(soft))
        if wanted and offered and wanted == offered:
            matched.append(soft)

    return {
        "catalogItemId": candidate.get("_id") or candidate.get("part"),
        "part": candidate.get("part"),
        "matchedOn": matched,
        "failedOn": failed,
        "eligible": not failed,
        "confidence": _score(matched, failed, opening),
    }


def _score(matched: list[str], failed: list[str], opening: dict[str, Any]) -> float:
    """Confidence bands from `.claude/rules/accuracy-trust.md`.

    An ineligible candidate scores 0.0 - not "low", but "not a match at all".
    """
    if failed:
        return 0.0
    # What the opening actually specified, and therefore what agreement is worth.
    asked = [
        field
        for field in ("fire_rating", "handing", "finish")
        if _norm(opening.get(field))
    ]
    if not asked:
        # Nothing to agree with. A plausible match that needs a human (0.40-0.74).
        return 0.55 if matched else 0.40
    agreed = sum(1 for field in asked if field in matched)
    if agreed == len(asked):
        return 0.95 if len(matched) > len(asked) else 0.90
    return 0.40 + 0.35 * (agreed / len(asked))


def candidates(
    opening: dict[str, Any],
    catalog: Iterable[dict[str, Any]],
    *,
    finish_equivalent=_same_finish,
    top_n: int = TOP_N,
) -> dict[str, Any]:
    """The top eligible candidates, plus why anything was excluded.

    `ratingConflict` is set when a rated opening had *every* candidate rejected on
    rating. That is the defect Matrix 7.3 names, and it belongs on the opening
    rather than buried in a rejected candidate list.
    """
    judged = [
        evaluate(opening, item, finish_equivalent=finish_equivalent) for item in catalog
    ]
    eligible = sorted(
        (row for row in judged if row["eligible"]),
        key=lambda row: (-row["confidence"], str(row.get("part") or "")),
    )
    rejected = [row for row in judged if not row["eligible"]]

    rated = _rating_minutes(opening.get("fire_rating")) is not None
    return {
        "matchCandidates": eligible[:top_n],
        "rejected": rejected,
        "ratingConflict": bool(rated and judged and not eligible
                              and any("fire_rating" in row["failedOn"] for row in rejected)),
        "ratingMissing": not rated,
        "autoMatched": bool(eligible) and eligible[0]["confidence"] >= CONFIDENCE_FLOOR,
        "needsReview": not eligible or eligible[0]["confidence"] < CONFIDENCE_FLOOR,
    }
