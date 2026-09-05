"""The review flags a run does not need judgment to produce.

`quality-reviewer` carried a thirteen-row table of findings and was asked to
apply it to every opening and every priced line. Most of those rows are not
judgment - "fire_rating is null", "cost_source is MANUAL", "margin is under its
band floor" are facts about a JSON file, and asking a model to enumerate them
over sixty openings gets a different answer each time it runs, misses some, and
costs a pass to find out.

So the mechanical rows are derived here, the same way every time, and the agent
is left the rows that genuinely need reading: reconciling counts against the
plans, spotting a value silently inferred from a neighbouring row, finding a
comparable prior quote, and writing the RFIs.

`merge` keeps both. A derived flag wins on the field it owns, and anything the
agent wrote that nothing here derives is carried through untouched.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cbc.core import calc
from cbc.core.paths import repo_root
from cbc.services import pricing

ROOT = repo_root()

# accuracy-trust.md: below this a match is flagged, never auto-accepted.
CONFIDENCE_FLOOR = 0.75

# Which cost sources describe a human still owing the quote something, and what
# the estimator is told about each.
UNFINISHED_COST_SOURCES = {
    "MANUAL": "Manual cut-off (NR-13) - priced by the estimator",
    "VENDOR_RFQ": "Awaiting vendor quote",
    "DISTRIBUTOR_MANUAL": "Distributor-bought - price may be stale",
}

# The fields whose absence makes an opening a question rather than a line.
REQUIRED_OPENING_FIELDS = {
    "fire_rating": "Missing fire rating",
    "handing": "Missing handing",
    "size": "Missing size",
}

# Ohio and Kentucky are taxed; the other 48 states and Canada are not. An unknown
# state is not "untaxed", it is unresolved.
TAXED_STATES = {"OH", "KY"}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _openings(payload: Any) -> list[dict]:
    """The schedule, in any of the shapes a pass has actually written it in."""
    if isinstance(payload, list):
        return [o for o in payload if isinstance(o, dict)]
    if isinstance(payload, dict):
        for key in ("openings", "doors", "schedule"):
            found = payload.get(key)
            if isinstance(found, list):
                return [o for o in found if isinstance(o, dict)]
    return []


def _flag(opening, field, severity, note, source_page=None) -> dict[str, Any]:
    return {
        "opening": opening,
        "field": field,
        "severity": severity,
        "source_page": source_page,
        "note": note,
        "derived": True,
    }


def _label(opening: dict) -> str:
    name = opening.get("door_number") or opening.get("mark") or "unknown opening"
    return str(name) if str(name).lower().startswith("door") else f"Door {name}"


def _opening_flags(openings: list[dict]) -> list[dict]:
    flags: list[dict] = []
    for opening in openings:
        label = _label(opening)
        page = opening.get("source_page")

        for field, note in REQUIRED_OPENING_FIELDS.items():
            if opening.get(field) in (None, "", []):
                flags.append(_flag(label, field, "high", note + " - estimator review", page))

        confidence = opening.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < CONFIDENCE_FLOOR:
            note = "Match confidence {:.2f} is below {}".format(confidence, CONFIDENCE_FLOOR)
            flags.append(_flag(label, "confidence", "high", note, page))

        # NFR-3: a record the estimator cannot find on the drawing is not traceable.
        if not opening.get("bbox"):
            flags.append(
                _flag(label, "bbox", "medium", "No location on the sheet (NFR-3)", page)
            )
    return flags


def _line_flags(lines: list[dict]) -> list[dict]:
    flags: list[dict] = []
    for line in lines:
        label = line.get("group") or line.get("line_id") or "unknown line"
        page = line.get("source_page")
        source = str(line.get("cost_source") or "").upper()

        if source in UNFINISHED_COST_SOURCES and line.get("cost") is None:
            flags.append(
                _flag(label, "cost", "medium", UNFINISHED_COST_SOURCES[source], page)
            )

        margin = line.get("margin")
        if isinstance(margin, (int, float)):
            band = pricing.band_for_division(line.get("division"))
            verdict = calc.validate_margin(band, float(margin))
            if verdict.get("flag") == "below_band":
                note = "Margin {:.0%} is below the {:.0%} floor for {} (NFR-8)".format(
                    margin, verdict["floor"], verdict["product_type"]
                )
                flags.append(_flag(label, "margin", "medium", note, page))

            # margin-governance.md: a below-band margin with a recorded reason is
            # a decision. Without one it is the thing the flag exists for.
            if line.get("margin_overridden") and not line.get("margin_override_reason"):
                flags.append(
                    _flag(label, "margin_override", "medium",
                          "Margin overridden with no reason recorded", page)
                )

        if line.get("substitution_note"):
            flags.append(
                _flag(label, "substitution", "medium",
                      "Direct-equal proposed: " + str(line["substitution_note"]), page)
            )
    return flags


def _scope_flags(scope: Any, metadata: Any) -> list[dict]:
    flags: list[dict] = []
    if isinstance(scope, dict):
        for item in scope.get("out_of_scope_items") or []:
            if not isinstance(item, dict):
                continue
            note = "Found in the bid set, not quoted: " + str(
                item.get("reason", "out of scope")
            )
            flags.append(
                _flag(item.get("item", "unknown item"), "out_of_scope", "low",
                      note, item.get("source_page"))
            )
        if scope.get("fire_ratings_present") is False:
            flags.append(
                _flag("bid set", "fire_rating", "high",
                      "No fire ratings anywhere in the set - Matrix 7.3 is open, "
                      "so do not assume unrated", None)
            )

    state = metadata.get("state") if isinstance(metadata, dict) else None
    if not state:
        flags.append(
            _flag("quote", "sales_tax", "medium",
                  "Project state unknown - sales tax unresolved")
        )
    return flags


def _no_scope_flags(schedule: Any, openings: list[dict]) -> list[dict]:
    """An empty take-off has to say so loudly, however it was phrased.

    The job passes validation in this case, so without a flag the estimator
    would see a green run and an empty quote and have to work out why. Keyed on
    the openings being empty rather than on any particular field, because the
    gate that keyed on a field name is what rejected a correct run.
    """
    if openings:
        return []
    reason = ""
    if isinstance(schedule, dict):
        reason = str(schedule.get("no_scope_reason") or "").strip()
        if not reason:
            for field in ("door_schedule_found", "schedule_found"):
                if schedule.get(field) is False:
                    reason = f"the take-off recorded {field}: false"
                    break
    return [
        _flag(
            "bid set",
            "no_scope",
            "high",
            "No Division 08 openings were found in this bid set"
            + (f": {reason}" if reason else " and no reason was recorded")
            + ". Confirm against the drawings before declining - an empty "
            "take-off and a missed schedule look identical on the quote.",
        )
    ]


def derive_flags(slug: str) -> list[dict]:
    """Every finding that follows from the artifacts, without a model."""
    project = ROOT / "projects" / slug
    schedule = _load(project / "extracted" / "door_schedule.json")
    openings = _openings(schedule)
    priced = _load(project / "priced" / "line_items.json")
    if isinstance(priced, list):
        lines = priced
    elif isinstance(priced, dict):
        lines = priced.get("lines", [])
    else:
        lines = []

    return [
        *_no_scope_flags(schedule, openings),
        *_opening_flags(openings),
        *_line_flags([line for line in lines if isinstance(line, dict)]),
        *_scope_flags(
            _load(project / "extracted" / "scope_summary.json"),
            _load(project / "extracted" / "scope_metadata.json"),
        ),
    ]


def merge(derived: list[dict], existing: Any) -> list[dict]:
    """Derived findings win their own field; the agent's own findings survive.

    The agent still writes what nothing here can see - a count that does not
    reconcile against the floor plans, a value inferred from a neighbouring row,
    a prior quote worth reusing, the RFIs. Those must not be dropped merely
    because they are not reproducible.
    """
    if isinstance(existing, dict):
        existing = existing.get("flags", [])
    if not isinstance(existing, list):
        existing = []

    owned = {(f.get("opening"), f.get("field")) for f in derived}
    kept = [
        f
        for f in existing
        if isinstance(f, dict) and (f.get("opening"), f.get("field")) not in owned
    ]
    return [*derived, *kept]


def write_flags(slug: str) -> int:
    """Derive, merge over what the pass wrote, and save. Returns the flag count."""
    path = ROOT / "projects" / slug / "review" / "review_flags.json"
    merged = merge(derive_flags(slug), _load(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return len(merged)
