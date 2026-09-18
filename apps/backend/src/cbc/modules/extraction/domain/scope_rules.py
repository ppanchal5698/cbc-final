"""What CBC quotes, as data rather than prose.

`.claude/rules/scope-boundaries.md` is the human-readable owner of this list and
stays authoritative. This is the same list in a form the take-off can apply, so
the decision does not depend on a model reading the rule and agreeing with itself.

That mattered: the same bid set, priced twice from the same inputs, produced 26
lines and then 12 - a different in/out split each run. Scope selection was the
single largest source of run-to-run variance in the pipeline.

The contract is the take-off's: **never silently wrong**. A row that matches an
out-of-scope rule is excluded with the rule that excluded it recorded; a row that
matches nothing at all is left `None` - unclassified, flagged, and the
estimator's call. Silence is not a decision.
"""
from __future__ import annotations

import re
from typing import Any, NamedTuple


class Rule(NamedTuple):
    key: str
    reason: str
    pattern: re.Pattern[str]


def _any_of(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


# Out of scope. Each reason is what the estimator tells the GC CBC is not covering,
# so it is written to be quoted, not paraphrased.
OUT_OF_SCOPE: tuple[Rule, ...] = (
    Rule(
        "storefront",
        "Aluminum / glass storefront - not a CBC estimating category",
        _any_of(r"STOREFRONT", r"ALUMINUM\s+STOREFRONT", r"FG-?\d+", r"CURTAIN\s*WALL"),
    ),
    Rule(
        "coiling_door",
        "Coiling / overhead / oversized door - separate HP division (garage doors)",
        _any_of(r"COILING", r"OVERHEAD\s+DOOR", r"ROLL(?:ING|-?UP)", r"SECTIONAL\s+DOOR",
                r"GRILLE\s+DOOR"),
    ),
    Rule(
        "engineered_wood",
        "Engineered wood - confirmed out of scope 14 Jul",
        _any_of(r"ENGINEERED\s+WOOD"),
    ),
    Rule(
        "metal_siding",
        "Metal siding / extruded aluminum - out of scope",
        _any_of(r"METAL\s+SIDING", r"EXTRUDED\s+ALUMIN(?:UM|IUM)"),
    ),
    Rule(
        "ceiling",
        "Ceiling tile and grid - another HP department",
        _any_of(r"CEILING\s+(?:TILE|GRID)", r"ACOUSTIC(?:AL)?\s+CEILING"),
    ),
    Rule(
        "tile_masonry",
        "Tile / thin brick / masonry - another HP department",
        _any_of(r"THIN\s+BRICK", r"MASONRY", r"CERAMIC\s+TILE", r"QUARRY\s+TILE"),
    ),
    Rule(
        "jl_industries",
        "JL Industries access doors and specialties - not CBC estimating",
        _any_of(r"JL\s+INDUSTRIES"),
    ),
    Rule(
        "scranton",
        "Scranton Products - access lost; would have to go through a costlier distributor",
        _any_of(r"SCRANTON"),
    ),
    Rule(
        "american_dryer",
        "American Dryer - no longer used; offer World Dryer or Excel XLERATOR",
        _any_of(r"AMERICAN\s+DRYER"),
    ),
)

# In scope, by what the schedule says the opening is made of. These are the
# materials CBC quotes: hollow metal, wood, and the laminate/FRP door faces.
IN_SCOPE_MATERIALS = {
    "HM": "hollow metal",
    "HMD": "hollow metal",
    "SCWD": "solid core wood",
    "WD": "wood",
    "W": "wood",
    "PL": "plastic laminate",
    "P.LAM": "plastic laminate",
    "PLAM": "plastic laminate",
    "FRP": "FRP",
    "ST": "steel",
    "STL": "steel",
    "HC": "hollow core wood",
}

# Aluminium is the storefront signal when it is the *door*. An aluminium frame
# around a wood or laminate door is ordinary - the Wendy's restroom doors are
# exactly that - so the frame alone never puts an opening out of scope.
_ALUMINIUM = {"AL", "ALUM", "ALUMINUM", "ALUMINIUM"}


class Verdict(NamedTuple):
    in_scope: bool | None  # None = the rules do not decide; a human must
    rule: str | None
    reason: str | None


def _text_of(opening: dict[str, Any]) -> str:
    return " ".join(
        str(opening.get(field) or "")
        for field in ("description", "room_name", "notes", "door_type",
                      "manufacturer", "series", "raw_row")
    )


def classify(opening: dict[str, Any]) -> Verdict:
    """Is CBC quoting this opening?

    Out-of-scope rules win: a coiling door is out however its materials read.
    """
    text = _text_of(opening)
    for rule in OUT_OF_SCOPE:
        if rule.pattern.search(text):
            return Verdict(False, rule.key, rule.reason)

    door = str(opening.get("door_material") or "").strip().upper()

    # An aluminium *leaf* is storefront, whatever the frame column says or does
    # not say. CBC quotes metal and wood doors; "metal" here means hollow metal
    # and steel, never aluminium. Requiring the frame to agree left four real
    # storefront doors on one bid sitting undecided because their frame cell was
    # blank.
    if door in _ALUMINIUM:
        rule = OUT_OF_SCOPE[0]
        return Verdict(False, rule.key, rule.reason)

    if door in IN_SCOPE_MATERIALS:
        return Verdict(True, f"material_{IN_SCOPE_MATERIALS[door].replace(' ', '_')}", None)

    # A door with no material column is not evidence of anything. Say so.
    if not door:
        return Verdict(None, None, "no door material on this row - scope not decided")
    return Verdict(None, None, f"door material {door!r} is not on CBC's in-scope list")


def apply_to(openings: list[dict[str, Any]]) -> dict[str, int]:
    """Stamp `in_scope` / `scope_rule` / `scope_reason` on each row, in place.

    An estimator's own decision is never overwritten: a row they confirmed or
    added by hand keeps whatever it says.
    """
    counts = {"in_scope": 0, "out_of_scope": 0, "undecided": 0, "preserved": 0}
    for opening in openings:
        if not isinstance(opening, dict):
            continue
        if opening.get("confirmed_by") or opening.get("added_by_hand"):
            counts["preserved"] += 1
            continue

        verdict = classify(opening)
        opening["in_scope"] = verdict.in_scope
        opening["scope_rule"] = verdict.rule
        opening["scope_reason"] = verdict.reason

        # Drop any verdict this function set last time before setting a new one.
        # Stripping only `out_of_scope*` let `scope_undecided` accumulate: the
        # seed reruns on every pass, so the flag list grew a duplicate a run.
        flags = [
            flag
            for flag in (opening.get("flags") or [])
            if not str(flag).startswith(("out_of_scope", "scope_undecided"))
        ]
        if verdict.in_scope is False:
            flags.append(f"out_of_scope_{verdict.rule}")
            counts["out_of_scope"] += 1
        elif verdict.in_scope is None:
            flags.append("scope_undecided")
            counts["undecided"] += 1
        else:
            counts["in_scope"] += 1
        opening["flags"] = flags
    return counts


def out_of_scope_items(openings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the review summary tells the GC CBC is not covering."""
    return [
        {
            "item": opening.get("door_number") or opening.get("mark"),
            "description": opening.get("description"),
            "reason": opening.get("scope_reason"),
            "rule": opening.get("scope_rule"),
            "source_page": opening.get("source_page"),
        }
        for opening in openings
        if isinstance(opening, dict) and opening.get("in_scope") is False
    ]


def _demo() -> None:
    """Runnable check on the rules that decide a real bid."""
    hm = classify({"door_material": "HM", "description": "90 min rated"})
    assert hm.in_scope is True, hm

    # The Wendy's restroom door: laminate leaf, aluminium frame. In scope.
    plam = classify({"door_material": "PL", "frame_material": "ALUM",
                     "description": "UNISEX WRM - Type B Interior P.LAM"})
    assert plam.in_scope is True, plam

    # An aluminium leaf is a storefront door, frame column or not.
    for frame in ("AL", None, ""):
        front = classify({"door_material": "AL", "frame_material": frame})
        assert front.in_scope is False and front.rule == "storefront", (frame, front)

    # An out-of-scope rule wins over the material column.
    coiling = classify({"door_material": "HM", "description": "COILING SERVICE DOOR"})
    assert coiling.in_scope is False and coiling.rule == "coiling_door", coiling

    # Never guessed: an unknown material is the estimator's call.
    unknown = classify({"door_material": "XYZ"})
    assert unknown.in_scope is None and unknown.reason, unknown
    assert classify({}).in_scope is None

    rows = [
        {"door_number": "01", "door_material": "AL", "frame_material": "AL"},
        {"door_number": "05", "door_material": "PL", "frame_material": "ALUM"},
        {"door_number": "99", "door_material": "XYZ"},
        {"door_number": "07", "door_material": "HM", "confirmed_by": "kevin@cbc.com"},
    ]
    counts = apply_to(rows)
    assert counts == {"in_scope": 1, "out_of_scope": 1, "undecided": 1, "preserved": 1}, counts
    assert "out_of_scope_storefront" in rows[0]["flags"]
    assert "scope_undecided" in rows[2]["flags"]
    assert "in_scope" not in rows[3], "an estimator's row is left alone"
    assert [i["item"] for i in out_of_scope_items(rows)] == ["01"]
    print("scope_rules demo OK")


if __name__ == "__main__":
    _demo()
