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

Every flag carries `blocking` beside `severity`. Severity is for display;
`blocking` is what the approval gate reads (`quoting` proposal readiness), and
only rules in this module set it. A finding a model wrote can inform the
estimator but cannot hold a quote, because nothing but an edit to that file
could ever clear it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cbc.modules.pricing.api import calc
from cbc.shared.paths import repo_root, storage_root
from cbc.modules.pricing.api import pricing, reference_library
from cbc.modules.pricing.api.confidence import AUTO_PROPOSE, CONFIDENCE_FLOOR
from cbc.shared import fire_rating

ROOT = repo_root()

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
    "finish": "Missing finish",
    "size": "Missing size",
}

# What to say once, for the bid, when no door on the schedule gives the field: the
# schedule does not carry it, and eight copies of "missing handing" at HIGH hid the
# one flag that mattered.
ABSENT_FROM_SCHEDULE = {
    "fire_rating": ("high", "No door on the schedule gives a fire rating - confirm the set has no rated openings"),
    "handing": ("medium", "The schedule gives no handing for any door - read it off the floor plan swings"),
    "finish": ("medium", "The door schedule gives no finish - each hardware item's finish is on its set"),
    "size": ("high", "No door on the schedule gives a size"),
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


def _flag(opening, field, severity, note, source_page=None, *, blocking=False) -> dict[str, Any]:
    return {
        "opening": opening,
        "field": field,
        "severity": severity,
        "source_page": source_page,
        "note": note,
        "derived": True,
        "blocking": blocking,
    }


def _label(opening: dict) -> str:
    name = opening.get("door_number") or opening.get("mark") or "unknown opening"
    return str(name) if str(name).lower().startswith("door") else f"Door {name}"


# The `<field>_missing` strings a pass writes onto the opening itself. These are
# what the line-items screen renders beside the row, and unlike review_flags.json
# nothing ever checked them against the row's own data - so a door carrying
# `finish: "US26D (626)"` reached the estimator flagged `finish_missing`, on every
# row of a real bid. A flag contradicted by the field it names is worse than no
# flag: it is the review queue telling the estimator to look at something that is
# already answered.
FIELD_MISSING_FLAGS = {field: f"{field}_missing" for field in REQUIRED_OPENING_FIELDS}


def reconcile_flags(opening: dict[str, Any]) -> list[str]:
    """The opening's flags with the contradicted `<field>_missing` ones removed.

    Deterministic and one-directional on purpose. A flag whose field is populated
    is dropped, because the data is the evidence and the flag is a claim about it.
    A flag that is *absent* while the field is empty is added, so a pass that
    simply forgot to flag cannot hide a gap. Everything else the pass wrote is
    left alone - it sees things this cannot.
    """
    flags = [f for f in (opening.get("flags") or []) if isinstance(f, str)]
    owned = set(FIELD_MISSING_FLAGS.values())
    kept = [f for f in flags if f not in owned]
    for field, flag in FIELD_MISSING_FLAGS.items():
        if opening.get(field) in (None, "", []):
            kept.append(flag)
    # Order is stable so an unchanged opening produces an unchanged artifact and
    # the version store does not record a new revision for nothing.
    seen: set[str] = set()
    return [f for f in kept if not (f in seen or seen.add(f))]


def _opening_flags(openings: list[dict], fire_ratings_present: bool = False) -> list[dict]:
    flags: list[dict] = []
    doors = [o for o in openings if not o.get("specialty")]
    # A field no door has is the schedule's silence, said once - unless rule 1 makes
    # each door's missing rating a stop of its own. A handing read off the plan is
    # not the schedule's: Evernorth's has no handing column, the plan gave 13 doors
    # theirs, and the other 21 came back one HIGH flag each.
    def on_schedule(opening: dict, field: str) -> bool:
        if field == "handing" and "handing_read_from_plan" in (opening.get("flags") or []):
            return False
        return opening.get(field) not in (None, "", [])

    absent = {field for field in REQUIRED_OPENING_FIELDS
              if len(doors) > 1 and not any(on_schedule(o, field) for o in doors)
              and not (field == "fire_rating" and fire_ratings_present)}
    for field in sorted(absent):
        severity, note = ABSENT_FROM_SCHEDULE[field]
        unread = [str(o.get("door_number") or o.get("mark") or "?") for o in doors
                  if o.get(field) in (None, "", [])]
        if len(unread) < len(doors):
            note = (f"{note}: {len(doors) - len(unread)} read off the plan - confirm them"
                    + (f"; still to read: doors {', '.join(unread)}" if unread else ""))
        flags.append(_flag("All doors", field, severity, note, doors[0].get("source_page")))
    for opening in openings:
        if opening.get("specialty"):
            continue  # Division 10 / FRP rows an export wrote here: not doors
        label = _label(opening)
        page = opening.get("source_page")

        for field, note in REQUIRED_OPENING_FIELDS.items():
            if field in absent:
                continue
            if opening.get(field) in (None, "", []):
                # In a set that rates its doors, an unrated opening may be a
                # rated door priced as an unrated one - a code problem, not a
                # price one (requirements 6.1, rule 1). In a set with no ratings
                # anywhere it is just a gap; on a door CBC is not quoting, nothing.
                blocking = (field == "fire_rating" and fire_ratings_present
                            and opening.get("in_scope") is not False)
                # As severe as the schedule's silence on it would be: a door's
                # handing or finish orders the part, its rating or size prices it.
                flags.append(
                    _flag(label, field, ABSENT_FROM_SCHEDULE[field][0], note + " - estimator review", page,
                          blocking=blocking)
                )

        keying = opening.get("keying")
        hw = " ".join(
            str(opening.get(k) or "")
            for k in ("hardware", "hardware_set", "hw_set")
        ).lower()
        implies_keying = any(
            token in hw for token in ("lock", "cylinder", "ic ", " ic", "storeroom", "keyway")
        )
        if implies_keying and not keying:
            flags.append(
                _flag(
                    label,
                    "keying",
                    "medium",
                    "Hardware implies keying/lock options but keying object is empty",
                    page,
                )
            )

        confidence = opening.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < CONFIDENCE_FLOOR:
            note = "Read at confidence {:.2f}, under {} - check the row against the sheet".format(
                confidence, CONFIDENCE_FLOOR)
            flags.append(_flag(label, "confidence", "high", note, page))

        # NFR-3: a record the estimator cannot find on the drawing is not traceable.
        if not opening.get("bbox"):
            flags.append(
                _flag(label, "bbox", "medium", "No location on the sheet (NFR-3)", page)
            )
    return flags


# Requirements 7.1 / NFR-2: a priced match under the auto-propose line is amber, and
# says what keeps it from certain. A price the model read has a note of its own.
_MATCH_WHY = {
    "model_chose_match": "the model chose it among rows at different prices",
    "series_match": "it is a size of the series the legend names, not the part itself",
    "direct_equal": "it is a direct equal for the part specified",
    "hardware_equal": "it is the equal on file for the Allegion part specified",
}


def _line_flags(lines: list[dict], excluded: list[dict] | None = None) -> list[dict]:
    flags: list[dict] = []
    for line in lines:
        label = line.get("group") or line.get("line_id") or "unknown line"
        page = line.get("source_page")
        source = str(line.get("cost_source") or "").upper()

        # .claude/guides/takeoff.md: an excluded vendor is not quoted at any price. The
        # tier sheet's `excluded` list is the record of who that is.
        vendor = re.sub(r"[^a-z0-9]", "", str(line.get("vendor") or line.get("manufacturer") or "").lower())
        for entry in excluded or []:
            name = str(entry.get("name") or "")
            if name and re.sub(r"[^a-z0-9]", "", name.lower()) in vendor:
                note = "{} is not quoted by CBC ({}) - remove the line and list it as out of scope".format(
                    name, entry.get("reason") or "excluded vendor"
                )
                flags.append(_flag(label, "out_of_scope", "high", note, page))

        if source in UNFINISHED_COST_SOURCES and line.get("cost") is None:
            # A line with no cost has no price; a quote cannot go out with one.
            # An alternate's missing price is visible but holds nothing: it is
            # not in the bid's total, and the bid can go out without it.
            flags.append(
                _flag(label, "cost", "medium", UNFINISHED_COST_SOURCES[source], page,
                      blocking=bool(line.get("in_base", not line.get("alternate_group"))))
            )

        if "carried_from_prior" in (line.get("flags") or []):
            # FR-1d: a templated bid starts as a copy of a prior job's quote, and a
            # row left over from that job must not go out on this one unseen.
            flags.append(_flag(label, "carried", "medium",
                               "Carried from {} - keep it if it applies to this job, or remove it".format(
                                   line.get("carried_from") or "a prior bid"),
                               page, blocking=True))

        # Requirements 6.1: a smoke-labeled assembly, and a 20-minute door tested
        # without hose stream - both the estimator's to confirm against the listing.
        if "smoke_gasketing_missing" in (line.get("flags") or []):
            flags.append(_flag(label, "smoke_gasketing", "high",
                               "Smoke-labeled doors cite this set, and it lists no gasketing - a smoke "
                               "assembly needs seals listed for smoke and draft control (UL 1784)", page))
        if "smoke_label" in (line.get("flags") or []) and str(line.get("line_id") or "").startswith("door:"):
            flags.append(_flag(label, "smoke_label", "medium",
                               "Smoke-labeled door (S label): the door, frame and gasketing must be "
                               "listed for smoke and draft control", page))
        match = line.get("match_confidence")
        why = next((text for flag, text in _MATCH_WHY.items() if flag in (line.get("flags") or [])), None)
        if why and line.get("cost") is not None and isinstance(match, (int, float)) and match < AUTO_PROPOSE:
            flags.append(_flag(label, "match", "medium",
                               "Matched at {:.2f}: {} - confirm the part".format(match, why), page))
        # A set priced by hand because the legend does not give it: Evernorth's schedule
        # cites groups 05, 06 and 08, and its manual lists 01 to 04.
        doors = ", ".join(str(d) for d in line.get("openings") or [])
        if "hardware_set_not_in_legend" in (line.get("flags") or []):
            flags.append(_flag(label, "hardware_set", "high",
                               "{} is cited by door{} {} but is not in the hardware legend - price it from "
                               "the schedule's notes, or ask for the set (RFI)".format(
                                   label, "s" if len(line.get("openings") or []) > 1 else "", doors), page))
        if "hardware_set_not_itemised" in (line.get("flags") or []):
            flags.append(_flag(label, "hardware_set", "medium",
                               "The legend names {} without its items - price the set from the sheet".format(label),
                               page))
        if "supply_unclear" in (line.get("flags") or []):
            flags.append(_flag(label, "supply", "medium",
                               "The schedule names another party here without saying who supplies the "
                               "item - confirm it is CBC's to quote", page))
        if "supply_read_by_model" in (line.get("flags") or []):
            flags.append(_flag(label, "supply", "medium",
                               "Moved to 'Supplied by others' on the model's reading of the schedule's "
                               "words - confirm, or move it back into the bid", page))
        if "price_read_by_model" in (line.get("flags") or []):
            flags.append(_flag(label, "cost", "medium",
                               "List price read off the price-book page by the model - confirm it against the sheet",
                               page))
        if "temperature_rise" in (line.get("flags") or []):
            flags.append(_flag(label, "fire_rating", "medium",
                               "Temperature-rise door (stair or exit enclosure) - quote it with its "
                               "temperature-rise core, and confirm the limit the schedule gives", page))
        if "no_hose_stream" in (line.get("flags") or []):
            flags.append(_flag(label, "fire_rating", "medium",
                               "20-minute door tested without hose stream - confirm the listing allows it here",
                               page))

        if "rated_set" in (line.get("flags") or []):
            flags.append(_flag(label, "fire_rating", "medium",
                               "This set serves fire-rated doors and the library does not record which parts "
                               "are listed - confirm its hinges, closer, latching and seals are listed for "
                               "the doors' rating", page))
        if "fire_exit_hardware_required" in (line.get("flags") or []):
            # Panic hardware on a rated door must be listed fire exit hardware
            # (requirements 6.1): a part priced off a list cannot say it is.
            flags.append(_flag(label, "fire_rating", "high",
                               "Exit device on a rated opening - confirm the part is listed fire exit hardware",
                               page))

        margin = line.get("margin")
        if isinstance(margin, (int, float)):
            band = pricing.band_for_division(line.get("division"))
            verdict = calc.validate_margin(band, float(margin))
            if verdict.get("flag") == "below_band":
                note = "Margin {:.0%} is below the {:.0%} floor for {} (NFR-8)".format(
                    margin, verdict["floor"], verdict["product_type"]
                )
                # A recorded reason makes it a decision (.claude/guides/pricing.md);
                # it stays visible but no longer holds the quote.
                flags.append(
                    _flag(label, "margin", "medium", note, page,
                          blocking=not line.get("margin_override_reason"))
                )

            # .claude/guides/pricing.md: a below-band margin with a recorded reason is
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
    if isinstance(metadata, dict) and metadata.get("brand_mismatch_warning"):
        flags.append(
            _flag("bid set", "project_identity", "critical",
                  "Unresolved brand/project identity mismatch: "
                  + str(metadata["brand_mismatch_warning"])
                  + ". Confirm the correct bid and documents before sending to the customer.",
                  blocking=True)
        )
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
            # The estimator's words, the same as the doors' own note - said once.
            flags.append(_flag("All doors", "fire_rating", *ABSENT_FROM_SCHEDULE["fire_rating"], None))

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


def _excluded_vendors() -> list[dict]:
    """The vendors the live tier sheet says CBC no longer quotes."""
    excluded = reference_library.load_vendor_tiers().get("excluded")
    return [e for e in excluded if isinstance(e, dict)] if isinstance(excluded, list) else []


def derive_flags(slug: str) -> list[dict]:
    """Every finding that follows from the artifacts, without a model."""
    project = storage_root() / slug
    schedule = _load(project / "extracted" / "line_items.json")
    openings = _openings(schedule)
    priced = _load(project / "priced" / "line_items.json")
    if isinstance(priced, list):
        lines = priced
    elif isinstance(priced, dict):
        lines = priced.get("lines", [])
    else:
        lines = []
    scope = _load(project / "extracted" / "scope_summary.json")
    # Whether the set rates its doors is read off the doors: the summary flag this
    # waited for was written by no code path, so rule 1 never held anything.
    rated = (isinstance(scope, dict) and scope.get("fire_ratings_present") is True) or any(
        fire_rating.is_rated(o.get("fire_rating")) for o in openings
        if o.get("in_scope") is not False and not o.get("specialty"))

    flags = [
        *_no_scope_flags(schedule, openings),
        *_opening_flags(openings, rated),
        *_line_flags([line for line in lines if isinstance(line, dict)], _excluded_vendors() if lines else []),
        *_scope_flags(scope, _load(project / "extracted" / "scope_metadata.json")),
        *_frp_constants_flags(project),
        *_document_not_parsed_flags(project),
        *_ocr_unavailable_flags(project),
    ]
    # The schedule's silence and the scope summary can both say "no door is rated":
    # one bid-level finding, said once. Two lines flagged alike are two findings.
    seen: set[tuple] = set()
    return [f for f in flags if f["opening"] != "All doors"
            or not ((key := (f["field"], f["note"])) in seen or seen.add(key))]


def _frp_constants_flags(project: Path) -> list[dict]:
    """FRP measured but not yet convertible: its quantities are not real yet.

    Panel, trim and adhesive counts come from geometry through CBC's conversion
    constants, and until those are set (Open Item 5) any FRP quantity on the
    quote is a placeholder rather than a count.
    """
    frp = _load(project / "extracted" / "frp_takeoff.json")
    if not (isinstance(frp, dict) and frp.get("areas")):
        return []
    if reference_library.load_frp_constants().get("status") != "PENDING":
        return []
    return [
        _flag("bid set", "frp_constants_pending", "high",
              "FRP was taken off but the FRP conversion constants are still PENDING - "
              "panel, trim and adhesive quantities cannot be computed yet",
              blocking=True)
    ]


def _ocr_unavailable_flags(project: Path) -> list[dict]:
    """Surface scanned pages where OCR assist could not run."""
    visual = _load(project / "extracted" / "_visual_pages.json")
    if not isinstance(visual, dict):
        return []
    flags: list[dict] = []
    for page in visual.get("pages") or []:
        if not isinstance(page, dict):
            continue
        status = page.get("ocr_status")
        if status not in ("unavailable", "failed"):
            continue
        source_page = page.get("source_page")
        note = (
            f"OCR {status} on {page.get('path')} page {source_page}; "
            "vision image is still required — text assist was empty"
        )
        flags.append(
            _flag(None, "ocr_unavailable", "info", note, source_page=source_page)
        )
    return flags


def _document_not_parsed_flags(project: Path) -> list[dict]:
    """NFR-2: a bid PDF that never got parsed blocks must be visible on review."""
    status = _load(project / "extracted" / "_parse_status.json")
    if not isinstance(status, dict):
        return []
    flags: list[dict] = []
    for doc in status.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        name = doc.get("filename") or "document"
        fallback = doc.get("fallbackPages") or []
        if fallback:
            # Advisory: the pages were read, just without LlamaParse's layout,
            # so a table may have come through as loose rows.
            note = (
                f"{name} pages {', '.join(str(p) for p in fallback)} were parsed "
                "locally after LlamaParse failed or ran past its deadline; "
                "check values read from them against the sheet"
            )
            flags.append(
                _flag(None, "parse_fallback", "medium", note, source_page=fallback[0])
            )
        state = doc.get("state")
        if state in (None, "parsed", "off"):
            continue
        note = (
            f"{name} was not read by the cloud parser ({state}); "
            "its pages were read from the PDF's own text instead"
        )
        if doc.get("error"):
            error = str(doc["error"])
            note = f"{note}. {error[:1].upper()}{error[1:]}"
        flags.append(
            _flag(None, "document_not_parsed", "info", note, source_page=None)
        )
    return flags


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
    # A derived flag in the saved file is this module's own output from the last
    # write, not the agent's. Keeping one whose condition has since cleared
    # would hold the approval gate after the estimator fixed what it named.
    # The agent's flags are kept but never block: see the module docstring.
    kept = [
        {**f, "blocking": False}
        for f in existing
        if isinstance(f, dict)
        and not f.get("derived")
        and (f.get("opening"), f.get("field")) not in owned
    ]
    return [*derived, *kept]


def _flags_path(slug: str) -> Path:
    return storage_root() / slug / "review" / "review_flags.json"


def read_flags(slug: str) -> list[dict]:
    """What write_flags would save - derived now, merged over the pass's file - without writing."""
    return merge(derive_flags(slug), _load(_flags_path(slug)))


def write_flags(slug: str) -> int:
    """Derive, merge over what the pass wrote, and save. Returns the flag count."""
    path = _flags_path(slug)
    merged = read_flags(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return len(merged)
