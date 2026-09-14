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
from cbc.modules.extraction.infrastructure import sheetmap
from cbc.shared import storage
from cbc.shared.storage import atomic_write_json

# How many door_schedule-role pages to try before giving up. The sheet map ranks
# them, and the first that yields openings is the schedule; the rest are usually a
# cover sheet listing "DOOR SCHEDULE" in its drawing index.
MAX_PAGES_TRIED = 4

SOURCE = "parse_schedule.py (deterministic pre-take-off)"


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

    candidates = sheetmap.pages_for_roles(sheets, "door_schedule")[:MAX_PAGES_TRIED]
    if not candidates:
        summary["note"] = "no page carries the door_schedule role"
        return summary

    parser = sheetmap._load_parse_schedule()

    for candidate in candidates:
        pdf = _resolve(slug, candidate["path"])
        if pdf is None:
            continue
        try:
            envelope = parser.openings_envelope(
                str(pdf), int(candidate["source_page"]), source_file=candidate["path"]
            )
        except Exception as exc:  # a bad page must not take the run down
            summary["note"] = f"{candidate['path']} p{candidate['source_page']}: {exc}"
            continue
        openings = envelope.get("openings") or []
        if not openings:
            continue

        previous = _existing(slug)
        prior = previous.get("openings") or previous.get("lines") or []
        merged = _merge(openings, [o for o in prior if isinstance(o, dict)])
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
        return summary

    summary["note"] = summary["note"] or "no openings parsed from any candidate page"
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

    `frp_in_scope` gates a whole phase, and it is a question the sheet map has
    already answered: FRP is in scope when some page carries the `frp` role.
    """
    path = storage.project_dir(slug) / "extracted" / "scope_summary.json"
    if path.is_file():
        return {"written": False, "note": "already present"}
    try:
        sheets = json.loads(sheetmap.sheetmap_path(slug).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"written": False, "note": "no _sheetmap.json"}

    frp_pages = sheetmap.pages_for_roles(sheets, "frp")
    schedule_pages = sheetmap.pages_for_roles(sheets, "door_schedule")
    payload = {
        "source": SOURCE,
        "seeded_at": sheetmap._now(),
        "frp_in_scope": bool(frp_pages),
        "door_schedule_found": bool(schedule_pages),
        "door_schedule_pages": [
            {"source_file": page["path"], "source_page": page["source_page"]}
            for page in schedule_pages[:MAX_PAGES_TRIED]
        ],
        "divisions": [],
        "out_of_scope_items": [],
        "flags": [
            "specs_not_read - divisions and out-of-scope items come from the "
            "specification, which no deterministic pass reads"
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return {"written": True, "frp_in_scope": payload["frp_in_scope"]}


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


def seed_frp_takeoff(slug: str) -> dict[str, Any]:
    """Write a `NOT_MEASURED` FRP take-off when FRP is in scope and none exists.

    Saying `frp_in_scope: true` creates an obligation: the run must produce
    `frp_takeoff.json` or fail validation. Nothing measures wall panels
    deterministically - perimeter, corners and wall height come off the drawings -
    so the honest artifact is one that says, in the file, that no pass has measured
    them yet. An empty quantity with a reason beats a missing file, which reads as
    "nobody looked" and stops the run.
    """
    path = storage.project_dir(slug) / "extracted" / "frp_takeoff.json"
    if path.is_file():
        return {"written": False, "note": "already present"}
    payload = {
        "source": SOURCE,
        "seeded_at": sheetmap._now(),
        "status": "NOT_MEASURED",
        "panels": [],
        "quantity": None,
        "flags": [
            "frp_not_measured - a sheet carries FRP, but perimeter, corner counts "
            "and wall height are read off the drawings and no pass has done that yet"
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return {"written": True}


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
