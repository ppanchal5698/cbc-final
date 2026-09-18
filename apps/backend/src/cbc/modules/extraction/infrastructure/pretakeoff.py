"""Run the take-off in code, before any model is asked anything.

`parse_schedule.py` already reads an opening schedule off a sheet deterministically:
door number, size, handing, fire rating, hardware group, and the bbox that lets the
estimator see the row it came from. Nothing about that needs a language model, and a
regex does not have an off day.

Until now the extraction prompt *asked* the model to run that script. A capable model
did; a 31B local model read three files, replied "I am ready to assist you with your
software engineering tasks", and the job died with no `door_schedule.json` at all.
The take-off was one `subprocess` call away the whole time.

So the worker runs it, the same way it already builds `_sheetmap.json`, and the model
starts from a filled schedule instead of a blank page. Its job shrinks from "produce
this file" to "check these rows against the sheet and fill what is null" - a task a
small model can actually do, and one whose failure mode is a missing improvement
rather than a missing artifact.

If pretakeoff finds no openings, the takeoff agent must still run `parse_schedule.py`
on remaining sheetmap pages before freehand authoring — never invent Opening keys
(`thickness`) or `page_size` arrays.

What this must never do is overwrite a person. Rows the estimator confirmed or added
by hand are decisions; a reseed carries them across untouched.
"""
from __future__ import annotations

import json
from typing import Any

from cbc.shared.paths import repo_root
from cbc.modules.extraction.domain import scope_rules
from cbc.modules.extraction.infrastructure import hardware_groups, sheetmap, specialty_parser
from cbc.shared import storage
from cbc.shared.storage import atomic_write_json

# How many schedule / candidate pages to try before giving up. The sheet map
# ranks them; confirmed door_schedule roles first, then text-poor candidates.
MAX_PAGES_TRIED = 8

SOURCE = "parse_schedule.py (deterministic pre-take-off)"


def _schedule_candidates(sheets: dict[str, Any]) -> list[dict[str, Any]]:
    """Ranked pages to parse: confirmed schedules first, then ID/text-poor candidates."""
    primary = sheetmap.pages_for_roles(sheets, "door_schedule")
    secondary = sheetmap.pages_for_roles(sheets, "door_schedule_candidate")
    seen: set[tuple[str, int]] = set()
    ordered: list[dict[str, Any]] = []
    for hit in [*primary, *secondary]:
        path = str(hit.get("path") or "")
        try:
            page = int(hit["source_page"])
        except (KeyError, TypeError, ValueError):
            continue
        key = (path, page)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(hit)
    return ordered[:MAX_PAGES_TRIED]


def _schedule_path(slug: str):
    return storage.project_dir(slug) / "extracted" / "door_schedule.json"


def _existing(slug: str) -> dict[str, Any]:
    path = _schedule_path(slug)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw, list):
        return {"openings": raw}
    return raw if isinstance(raw, dict) else {}


def _is_a_decision(opening: dict[str, Any]) -> bool:
    """Did a person put this row here, or confirm it?"""
    return bool(opening.get("confirmed_by")) or bool(opening.get("added_by_hand"))


def _key(opening: dict[str, Any]) -> str:
    number = opening.get("door_number") or opening.get("mark")
    return str(number).strip().upper() if number else ""


def _blend(parsed: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Re-parsed values where the parser read something; the previous pass elsewhere.

    A parser null means "this column was unreadable", which is no information at
    all - so it must not erase a handing or fire rating that a previous pass read
    off the sheet. Where the parser *did* read a value it wins, because it is the
    one reading the drawing this time round.
    """
    kept = {key: value for key, value in parsed.items() if value not in (None, "", [])}
    return {**prior, **kept}


def _merge(parsed: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parsed rows, with every human decision - and every earlier finding - kept."""
    prior = {_key(o): o for o in existing if _key(o)}
    decisions = {key: o for key, o in prior.items() if _is_a_decision(o)}
    merged = []
    for opening in parsed:
        key = _key(opening)
        if key in decisions:
            merged.append(decisions[key])  # a person settled this row
        elif key in prior:
            merged.append(_blend(opening, prior[key]))
        else:
            merged.append(opening)
    seen = {_key(o) for o in merged}
    # A hand-added opening has no row on the sheet to re-parse, so it is only ever
    # in `existing`. Dropping it would delete the estimator's own work.
    merged.extend(o for key, o in decisions.items() if key not in seen)
    return merged


def _resolve(slug: str, path: str):
    """A sheet-map path (`projects/<slug>/uploads/raw/x.pdf`) as a real file.

    The map records the path a pdf-tools call takes, which is repo-relative. That
    is not the same frame as STORAGE_ROOT: on this host `projects/` is a junction
    to `data/projects`, and joining the two frames produced
    `data/projects/projects/test/...` - every candidate missed, and a take-off
    that reported "no openings" against a schedule sitting on page 14.
    """
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    for candidate in (
        repo_root() / path,
        storage.project_dir(slug) / "uploads" / "raw" / name,
    ):
        if candidate.is_file():
            return candidate
    return None


def seed_door_schedule(slug: str) -> dict[str, Any]:
    """Write `extracted/door_schedule.json` from the drawings, in code.

    Returns a summary: which page was read, how many openings, how many human rows
    were preserved. Never raises - a bid set whose schedule cannot be parsed is a
    job for the model, not a reason to fail the run before it starts.
    """
    summary: dict[str, Any] = {"openings": 0, "page": None, "preserved": 0, "note": None}
    try:
        sheets = json.loads(sheetmap.sheetmap_path(slug).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary["note"] = "no _sheetmap.json; nothing to read"
        return summary

    candidates = _schedule_candidates(sheets)
    if not candidates:
        summary["note"] = "no page carries the door_schedule or door_schedule_candidate role"
        return summary

    parser = sheetmap._load_parse_schedule()

    # Read every candidate and keep the best, rather than the first that yields a
    # row. Taking the first meant one bad page decided the whole take-off: on a
    # real set the schedule sheet raised inside the parser, the error was noted
    # and skipped, and the next candidate's single stray row became the take-off -
    # one junk opening where the sheet had four.
    best: tuple[dict[str, Any], list[dict[str, Any]]] | None = None
    errors: list[str] = []
    for candidate in candidates:
        pdf = _resolve(slug, candidate["path"])
        if pdf is None:
            continue
        try:
            envelope = parser.openings_envelope(
                str(pdf), int(candidate["source_page"]), source_file=candidate["path"]
            )
        except Exception as exc:  # a bad page must not take the run down
            errors.append(f"{candidate['path']} p{candidate['source_page']}: {exc}")
            continue
        found = envelope.get("openings") or []
        if found and (best is None or len(found) > len(best[1])):
            best = (candidate, found)

    if best is not None:
        candidate, openings = best

        previous = _existing(slug)
        prior = previous.get("openings") or previous.get("lines") or []
        merged = _merge(openings, [o for o in prior if isinstance(o, dict)])
        # Decide scope here, in code. Leaving it to the pass is what made the
        # same bid come back with 26 lines one run and 12 the next.
        scope = scope_rules.apply_to(merged)
        summary["scope"] = scope
        # A candidate that raised is a finding even when another page parsed: it
        # is usually the better sheet, and silence there is how one junk row from
        # a lesser page became the take-off.
        summary["errors"] = errors
        summary.update(
            openings=len(merged),
            page=candidate["source_page"],
            preserved=len(merged) - len(openings),
            note=None,
        )

        payload = {
            **previous,
            "source_file": candidate["path"],
            "source_page": candidate["source_page"],
            "source": SOURCE,
            "seeded_at": sheetmap._now(),
            "openings": merged,
        }
        payload.pop("lines", None)
        path = _schedule_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload)

        # What the sheet actually said, kept where nothing will overwrite it.
        #
        # `door_schedule.json` is the working document: the pass patches it, and
        # confirming in the Ops-Hub exports the estimator's version straight over
        # it. That is right - pricing must price what was approved - but it means
        # that the moment anyone confirms, the reading the parser took no longer
        # exists anywhere, and "what did the drawing say before we changed it?"
        # becomes unanswerable. This file answers it.
        # Scope is decided in code too, so it belongs in the snapshot - otherwise
        # a diff against the working document reports a change nobody made. On a
        # copy, because `_merge` hands back the parsed dicts for new rows and
        # stamping them here would reach into the file already written above.
        import copy

        raw = copy.deepcopy(openings)
        scope_rules.apply_to(raw)
        snapshot = path.with_name("door_schedule.extracted.json")
        atomic_write_json(snapshot, {
            "source": SOURCE,
            "source_file": candidate["path"],
            "source_page": candidate["source_page"],
            "extracted_at": sheetmap._now(),
            "note": (
                "The deterministic parse, before any model patch or estimator "
                "edit. Never overwritten - diff door_schedule.json against this "
                "to see what a pass or a person changed."
            ),
            "openings": raw,
        })
        return summary

    # Nothing parsed anywhere. Say which pages were tried and what each one did,
    # so "no openings" is a report rather than a shrug.
    summary["note"] = "; ".join(errors) or "no openings parsed from any candidate page"
    summary["errors"] = errors
    return summary


def seed_hardware_groups(slug: str) -> dict[str, Any]:
    """Write `extracted/hardware_sets.json` from the legend, in code.

    A door schedule cites a hardware group per opening and nothing ever read the
    legend that says what those groups contain, so the parts stayed in the PDF:
    two bid sets reached pricing with no manufacturer parts at all and a row of
    blank MANUAL lines. On the sheet that prompted this, 11 sets and 83 items
    come out, 84% of them carrying a part number.

    Never raises. A legend that will not parse is a job for the model, not a
    reason to fail the run before it starts.
    """
    summary: dict[str, Any] = {"sets": 0, "items": 0, "pages": [], "note": None}
    try:
        sheets = json.loads(sheetmap.sheetmap_path(slug).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary["note"] = "no _sheetmap.json; nothing to read"
        return summary

    # sheetmap already tags the legend sheet; scope_summary never read the role,
    # which is also why `hardware_group_pages` was always empty.
    candidates = sheetmap.pages_for_roles(sheets, "hardware")
    if not candidates:
        summary["note"] = "no page carries the hardware role"
        return summary

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates[:MAX_PAGES_TRIED]:
        pdf = _resolve(slug, candidate["path"])
        if pdf is None:
            continue
        try:
            found = hardware_groups.groups_on_page(pdf, int(candidate["source_page"]))
        except Exception as exc:  # a bad page must not take the run down
            summary["note"] = f"{candidate['path']} p{candidate['source_page']}: {exc}"
            continue
        for entry in found.get("sets") or []:
            key = str(entry.get("hardware_set") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            entry["source_file"] = candidate["path"]
            collected.append(entry)
        if found.get("sets"):
            summary["pages"].append(candidate["source_page"])

    if not collected:
        summary["note"] = summary["note"] or "no hardware legend parsed from any candidate page"
        return summary

    path = storage.project_dir(slug) / "extracted" / "hardware_sets.json"
    payload = {
        "source": SOURCE,
        "seeded_at": sheetmap._now(),
        "pages_read": summary["pages"],
        "sets": collected,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    summary.update(sets=len(collected), items=sum(len(e.get("items") or []) for e in collected))
    return summary


# ── the other two artifacts a run is required to produce ────────────────────
#
# `extract_bid_set` fails validation without scope_metadata.json and
# scope_summary.json. A model that writes neither leaves the estimator with
# nothing at all, so the worker writes a truthful floor for both and lets the
# model improve on it. Truthful means: what is actually known goes in, what is
# not is null with a flag saying so - never a guess (.claude/rules/accuracy-trust.md).


def seed_scope_summary(slug: str) -> dict[str, Any]:
    """Write `extracted/scope_summary.json` from the sheet map.

    `frp_in_scope` / `div10_in_scope` gate specialty phases. The sheet map has
    already answered those questions via role tags.
    """
    path = storage.project_dir(slug) / "extracted" / "scope_summary.json"
    if path.is_file():
        # An existing summary is left alone - a real pass beats this floor - but
        # the in-scope flags still have to come back, because they are what gates
        # the FRP and Div 10 seeds. Returning only `written: False` meant that on
        # every re-run those two artifacts were never seeded at all, and the
        # specialists started from a blank page again.
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        return {
            "written": False,
            "note": "already present",
            "frp_in_scope": bool(existing.get("frp_in_scope")),
            "div10_in_scope": bool(existing.get("div10_in_scope")),
        }
    try:
        sheets = json.loads(sheetmap.sheetmap_path(slug).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"written": False, "note": "no _sheetmap.json"}

    frp_pages = sheetmap.pages_for_roles(sheets, "frp")
    div10_pages = sheetmap.pages_for_roles(sheets, "div10")
    schedule_pages = sheetmap.pages_for_roles(sheets, "door_schedule")
    # The `hardware` role has been on the sheet map all along; this never read it,
    # so `hardware_group_pages` came out `[]` on every bid and the matcher was
    # told the legend was nowhere.
    hardware_pages = sheetmap.pages_for_roles(sheets, "hardware")
    payload = {
        "source": SOURCE,
        "seeded_at": sheetmap._now(),
        "frp_in_scope": bool(frp_pages),
        "div10_in_scope": bool(div10_pages),
        "door_schedule_found": bool(schedule_pages),
        "door_schedule_pages": [
            {"source_file": page["path"], "source_page": page["source_page"]}
            for page in schedule_pages[:MAX_PAGES_TRIED]
        ],
        "div10_schedule_pages": [
            {"source_file": page["path"], "source_page": page["source_page"]}
            for page in div10_pages[:MAX_PAGES_TRIED]
        ],
        "hardware_groups_found": bool(hardware_pages),
        "hardware_group_pages": [
            {"source_file": page["path"], "source_page": page["source_page"]}
            for page in hardware_pages[:MAX_PAGES_TRIED]
        ],
        "divisions": [],
        # What CBC is not covering, decided by the rules rather than by a pass
        # re-reading `scope-boundaries.md` and agreeing with itself.
        "out_of_scope_items": scope_rules.out_of_scope_items(
            (_existing(slug).get("openings") or [])
        ),
        "flags": [
            "specs_not_read - divisions and out-of-scope items come from the "
            "specification, which no deterministic pass reads"
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return {
        "written": True,
        "frp_in_scope": payload["frp_in_scope"],
        "div10_in_scope": payload["div10_in_scope"],
    }


# The Ops-Hub create form is the only non-PDF source of these, and the importer
# fills project fields only where they are still empty - so echoing them back is
# safe, and it means a run always has the file even when nothing read the title
# block.
_OPS_HUB_FIELDS = (
    ("name", "project_name"),
    ("brand", "brand"),
    ("state", "state"),
    ("location", "location"),
    ("address", "address"),
    ("city", "city"),
    ("architect", "architect"),
    ("gc", "gc"),
    ("initiator", "initiator"),
    ("projectNumber", "project_number"),
)


def seed_scope_metadata(slug: str, project: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write `extracted/scope_metadata.json` with what the Ops-Hub already knows.

    Every field the job record does not carry is written as null and flagged, so a
    later pass can see exactly what is still owed rather than inferring that an
    absent key means "nothing to find".
    """
    path = storage.project_dir(slug) / "extracted" / "scope_metadata.json"
    if path.is_file():
        return {"written": False, "note": "already present"}

    record = project or {}
    payload: dict[str, Any] = {"source": SOURCE, "seeded_at": sheetmap._now()}
    unread: list[str] = []
    for ops_key, agent_key in _OPS_HUB_FIELDS:
        value = record.get(ops_key)
        payload[agent_key] = value if value not in (None, "", []) else None
        if payload[agent_key] is None:
            unread.append(agent_key)
    payload["source_files"] = []
    payload["field_sources"] = {}
    payload["flags"] = [
        f"title_block_not_read - {field} is null because no pass has read the "
        f"drawings for it, not because the drawings are silent"
        for field in unread
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return {"written": True, "unread": len(unread)}


def _specialty_pages(slug: str, role: str) -> tuple[Any, list[int], str | None]:
    """The one PDF and the pages `sheetmap` tags for `role`.

    Both specialty parsers read whole pages rather than a ranked schedule, so a
    single document and its page list is all they need. More than one raw PDF is
    the `_resolve` case already handled per candidate - here the first that
    resolves wins and the rest of its pages come along.
    """
    try:
        sheets = json.loads(sheetmap.sheetmap_path(slug).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, [], "no _sheetmap.json; nothing to read"

    candidates = sheetmap.pages_for_roles(sheets, role)
    if not candidates:
        return None, [], f"no page carries the {role} role"

    pdf = None
    pages: list[int] = []
    for candidate in candidates[:MAX_PAGES_TRIED]:
        resolved = _resolve(slug, candidate["path"])
        if resolved is None:
            continue
        if pdf is None:
            pdf = resolved
        if resolved == pdf:
            pages.append(int(candidate["source_page"]))
    if pdf is None:
        return None, [], f"no {role} page resolved to a PDF on disk"
    return pdf, pages, None


def _seeded_by_us(path) -> bool:
    """True when the file on disk is this seed's own output and safe to replace.

    A reseed must be deterministic, so it rewrites what it wrote last time. It
    must never overwrite what an estimator or an agent put there - that is a
    decision, not an input (same contract as `_is_a_decision`).
    """
    if not path.is_file():
        return True
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("source") == SOURCE
    except (OSError, json.JSONDecodeError):
        return False


def seed_frp_takeoff(slug: str) -> dict[str, Any]:
    """Write `extracted/frp_takeoff.json` from the specification, in code.

    This was a placeholder - `NOT_MEASURED` with an empty `areas` - so every FRP
    field on a quote came from a model inventing it. The specification is
    machine-readable: it names the product and, when it names one, the vendor.
    Geometry is not: perimeter, corner counts and wall height come off scaled
    interior elevations, and those stay null and flagged, because a guessed
    linear-foot figure prices a wall that does not exist.

    Never raises. A sheet that will not parse is a job for the model.
    """
    path = storage.project_dir(slug) / "extracted" / "frp_takeoff.json"
    if not _seeded_by_us(path):
        return {"written": False, "note": "already present and not ours to replace"}

    pdf, pages, note = _specialty_pages(slug, "frp")
    payload: dict[str, Any]
    if pdf is None:
        payload = _frp_placeholder(note)
    else:
        try:
            payload = specialty_parser.frp_findings(pdf, pages)
            payload["source_file"] = pdf.name
        except Exception as exc:  # a bad page must not take the run down
            payload = _frp_placeholder(f"{pdf.name}: {exc}")

    payload["source"] = SOURCE
    payload["seeded_at"] = sheetmap._now()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return {"written": True, "status": payload["status"], "note": note}


def _frp_placeholder(note: str | None) -> dict[str, Any]:
    """What the artifact says when nothing could be read. Still not a guess."""
    return {
        "frp_in_scope": True,
        "status": "NOT_MEASURED",
        "areas": [],
        "panels": [],
        "quantities": None,
        "quantity": None,
        "flags": [
            "frp_not_measured - a sheet carries FRP, but perimeter, corner counts "
            "and wall height are read off the drawings and no pass has done that yet"
        ],
        "note": note,
    }


def seed_div10_takeoff(slug: str) -> dict[str, Any]:
    """Write `extracted/div10_takeoff.json` from the accessory schedule, in code.

    This was a placeholder too. What a schedule identifies - product type,
    manufacturer, model - is read here; what it does not carry, chiefly counts,
    stays null and flagged, because counting accessories means reading interior
    elevations and a default of 1 quotes one grab bar for a building.
    """
    path = storage.project_dir(slug) / "extracted" / "div10_takeoff.json"
    if not _seeded_by_us(path):
        return {"written": False, "note": "already present and not ours to replace"}

    pdf, pages, note = _specialty_pages(slug, "div10")
    payload: dict[str, Any]
    if pdf is None:
        payload = _div10_placeholder(note)
    else:
        try:
            payload = specialty_parser.div10_envelope(pdf, pages)
        except Exception as exc:
            payload = _div10_placeholder(f"{pdf.name}: {exc}")

    payload["div10_in_scope"] = True
    payload["source"] = SOURCE
    payload["seeded_at"] = sheetmap._now()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return {
        "written": True,
        "status": payload["status"],
        "items": len(payload.get("items") or []),
        "mentions": len(payload.get("mentions") or []),
        "note": note,
    }


def _div10_placeholder(note: str | None) -> dict[str, Any]:
    return {
        "status": "NOT_EXTRACTED",
        "items": [],
        "mentions": [],
        "flags": [
            "div10_not_extracted - Div 10 specialty pages are in the set, but "
            "product type, manufacturer, location and counts have not been read yet"
        ],
        "note": note,
    }


def _demo() -> None:
    """The merge is the only branching logic here, and it guards estimator work."""
    parsed = [
        {"door_number": "01", "size": "3070", "confidence": 0.55},
        {"door_number": "02", "size": "3070", "confidence": 0.55},
    ]
    existing = [
        {"door_number": "01", "size": "3068", "confirmed_by": "kevin@cbc.com"},
        {"door_number": "99", "size": "6070", "added_by_hand": True},
    ]
    merged = _merge(parsed, existing)
    by_number = {o["door_number"]: o for o in merged}
    assert by_number["01"]["size"] == "3068", "a confirmed row was overwritten by a reparse"
    assert by_number["02"]["size"] == "3070", "a fresh row did not come through"
    assert "99" in by_number, "a hand-added opening was dropped"
    assert len(merged) == 3

    # An earlier pass read a handing off the sheet; the parser could not. Re-seeding
    # must not throw that away, but must still re-read what it can.
    enriched = _merge(
        [{"door_number": "02", "size": "3070", "handing": None, "bbox": [1, 2, 3, 4]}],
        [{"door_number": "02", "size": "wrong", "handing": "LH", "glass": "TEMP."}],
    )[0]
    assert enriched["handing"] == "LH", "a parser null erased a value read from the sheet"
    assert enriched["glass"] == "TEMP.", "a field the parser does not produce was dropped"
    assert enriched["size"] == "3070", "the fresh parse did not win where it read a value"
    assert enriched["bbox"] == [1, 2, 3, 4]

    assert _merge(parsed, []) == parsed
    assert _key({"mark": " a1 "}) == "A1"
    assert not _is_a_decision({"door_number": "01"})

    # A seed must never claim to have read something it did not.
    import tempfile
    from pathlib import Path

    from cbc.shared.config import settings

    previous = settings.storage_root
    with tempfile.TemporaryDirectory() as scratch:
        settings.storage_root = Path(scratch)
        (Path(scratch) / "seedcheck" / "extracted").mkdir(parents=True)
        result = seed_scope_metadata("seedcheck", {"name": "Test", "state": "OH"})
        assert result["written"]
        written = json.loads(
            (Path(scratch) / "seedcheck" / "extracted" / "scope_metadata.json").read_text()
        )
        assert written["project_name"] == "Test"
        assert written["architect"] is None, "an unread field must stay null"
        assert any("architect" in flag for flag in written["flags"]), "null with no flag"
        assert not seed_scope_metadata("seedcheck", {})["written"], "overwrote an existing file"
    settings.storage_root = previous
    print("pretakeoff demo OK")


if __name__ == "__main__":
    _demo()
