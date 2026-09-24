#!/usr/bin/env python3
"""Score an extraction against a hand-checked reference.

    python scripts/score_extraction.py --generate <pdf> --page 14   # draft a golden file
    python scripts/score_extraction.py --project autopilot_smoke_test
    python scripts/score_extraction.py --all

Three numbers, and only one of them is allowed to be non-zero-tolerance:

  silent errors  a field is filled in and disagrees with the reference. This is the
                 only unacceptable class - a confidently wrong fire rating reaches a
                 quote and nobody knows to check it. Must be 0.
  coverage       of the fields the document actually contains, how many were read.
  honesty        of the fields the document does not contain, how many were left
                 null *and* flagged rather than invented.

A blank is not an error. On the Dutch Bros fixture the door schedule carries no
handing, finish or fire rating at all - `parse_schedule.py` finds none either - so
the correct output there is a flagged blank, and scoring it as a miss would push
the system toward guessing, which is the failure mode NFR-2 exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from cbc.shared.paths import storage_root

ROOT = Path(__file__).resolve().parents[1]

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"


def _load_parse_schedule():
    import importlib.util

    # `.claude` sits at the repository root, not under apps/backend. Resolving it
    # against ROOT meant `--generate` raised FileNotFoundError from any working
    # directory, so the one command that drafts a golden could not be run.
    from cbc.shared.paths import repo_root

    path = (
        repo_root() / ".claude" / "skills" / "extract-door-schedule" / "scripts"
        / "parse_schedule.py"
    )
    spec = importlib.util.spec_from_file_location("parse_schedule", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# The fields a golden file pins. `door_number` and `source_page` are the identity
# and the provenance; the rest are what an estimator reads off the schedule.
# What the gate actually checks. `width`, `height`, `room_name` and the two
# material columns were missing from this tuple, which is why the harness stayed
# green for so long while the parser read every one of them from the wrong
# column: `width` came back "VESTIBULE", `height` came back "HM". A field the
# gate does not score is a field nothing is defending.
SCORED_FIELDS = (
    "door_number", "size", "width", "height", "room_name",
    "handing", "finish", "fire_rating", "hardware_set", "door_type",
    "frame_type", "door_material", "frame_material", "wall_type", "source_page",
)


def _openings(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return payload.get("openings") or []
    return payload if isinstance(payload, list) else []


def _key(opening: dict[str, Any]) -> str:
    """The grouping key, whichever of the two names it arrived under."""
    return str(opening.get("door_number") or opening.get("mark") or "").strip()


def _normalise(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value).strip().upper()


# ── generating a draft reference ───────────────────────────────────────────


def _candidates(slug: str | None) -> dict[str, dict[str, Any]]:
    """Values a previous run read, keyed by door number.

    The deterministic parser is the spine of the reference because it is
    reproducible, but it does not read every column: on the Dutch Bros fixture it
    leaves door_type, frame_type and wall_type null while a model run read
    "TEMP. HM HMD", "1" and "A" off the same sheet. Those are candidates, not
    truth - they are offered so the review is a confirmation rather than a hunt
    through the PDF, and every one is marked `needs_confirming`.
    """
    if not slug:
        return {}
    schedule = storage_root() / slug / "extracted" / "line_items.json"
    if not schedule.exists():
        return {}
    payload = json.loads(schedule.read_text(encoding="utf-8"))
    return {_key(o): o for o in _openings(payload) if _key(o)}


def generate(pdf: Path, page: int, from_run: str | None = None) -> dict[str, Any]:
    """Draft a golden file from the deterministic parser.

    Everything the parser could not find is written as null with `unknown: true`,
    which is a claim for a human to confirm: either the document really does not
    say, or the parser is missing it. Only a person can tell those apart, which is
    why this output is a draft and not a reference until it has been reviewed.
    """
    parse_schedule = _load_parse_schedule()

    rows = parse_schedule.schedule_rows(str(pdf), page)
    candidates = _candidates(from_run)
    openings = []
    for row in rows:
        door = _key(row)
        seen = candidates.get(door, {})
        record: dict[str, Any] = {"door_number": door, "source_page": page}
        unknown, confirm = [], []
        for field in SCORED_FIELDS:
            if field in ("door_number", "source_page"):
                continue
            value = row.get(field)
            if value in (None, ""):
                value = seen.get(field)
                if value not in (None, ""):
                    confirm.append(field)
            record[field] = value if value not in (None, "") else None
            if record[field] is None:
                unknown.append(field)
        record["unknown"] = unknown
        if confirm:
            record["needs_confirming"] = confirm
        openings.append(record)

    return {
        "source_file": pdf.name,
        "source_page": page,
        "reviewed_by": None,
        "note": (
            "DRAFT - generated by scripts/score_extraction.py --generate from the "
            "deterministic parser. Every field in `unknown` needs a human to say "
            "whether the document is silent on it or the parser missed it. Set "
            "reviewed_by once checked; until then the accuracy gate treats this as "
            "provisional."
        ),
        "openings": openings,
    }


# ── scoring ────────────────────────────────────────────────────────────────


def score(actual: list[dict[str, Any]], golden: dict[str, Any]) -> dict[str, Any]:
    expected = {_key(o): o for o in golden.get("openings", [])}
    found = {_key(o): o for o in actual if _key(o)}

    silent: list[str] = []
    covered = available = honest = absent = 0

    for door, want in expected.items():
        got = found.get(door)
        if got is None:
            # A whole opening that was not read is a miss, not a silent error -
            # nothing wrong was asserted. It still fails coverage.
            available += sum(1 for f in SCORED_FIELDS if want.get(f) is not None)
            continue

        unknown = set(want.get("unknown") or [])
        for field in SCORED_FIELDS:
            wanted, actually = _normalise(want.get(field)), _normalise(got.get(field))
            if field in unknown or wanted is None:
                absent += 1
                # Honest only if it was left blank. A value invented where the
                # document says nothing is the worst case of all.
                if actually is None:
                    honest += 1
                else:
                    silent.append(
                        f"{door}.{field}: document says nothing, run asserted {actually!r}"
                    )
                continue
            available += 1
            if actually == wanted:
                covered += 1
            elif actually is not None:
                silent.append(f"{door}.{field}: expected {wanted!r}, got {actually!r}")

    return {
        "openings_expected": len(expected),
        "openings_found": len(found),
        "missing_openings": sorted(set(expected) - set(found)),
        "extra_openings": sorted(set(found) - set(expected)),
        "silent_errors": silent,
        "coverage": round(covered / available, 3) if available else 1.0,
        "honesty": round(honest / absent, 3) if absent else 1.0,
        "provisional": golden.get("reviewed_by") is None,
    }


def score_project(slug: str) -> dict[str, Any] | None:
    schedule = storage_root() / slug / "extracted" / "line_items.json"
    if not schedule.exists():
        return None
    payload = json.loads(schedule.read_text(encoding="utf-8"))

    # The schedule should name the PDF it was read from (NFR-3), but a run can omit
    # it, so fall back to what the bid actually holds. Guessing from the project
    # slug scored the run against a reference that does not exist.
    names = []
    source = (payload.get("source_file") if isinstance(payload, dict) else None) or ""
    if source:
        names.append(Path(source).stem)
    names += [pdf.stem for pdf in sorted((storage_root() / slug / "uploads" / "raw").glob("*.pdf"))]

    for name in names:
        golden_file = GOLDEN_DIR / f"{name}.json"
        if golden_file.exists():
            return score(_openings(payload), json.loads(golden_file.read_text(encoding="utf-8")))
    tried = ", ".join(f"{n}.json" for n in names) or "nothing to try"
    return {"error": f"no reference in tests/fixtures/golden/ (tried: {tried})"}


def _report(label: str, result: dict[str, Any]) -> int:
    print(f"\n{label}")
    if "error" in result:
        print(f"  {result['error']}")
        return 0
    print(f"  openings      {result['openings_found']}/{result['openings_expected']}"
          + (f"  missing {result['missing_openings']}" if result["missing_openings"] else ""))
    print(f"  coverage      {result['coverage']:.0%}   (fields the document has, that were read)")
    print(f"  honesty       {result['honesty']:.0%}   (fields it does not have, left blank)")
    print(f"  silent errors {len(result['silent_errors'])}")
    for problem in result["silent_errors"][:10]:
        print(f"     - {problem}")
    if result["provisional"]:
        print("  NOTE: reference is a draft (reviewed_by is null)")
    return 1 if result["silent_errors"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", type=Path, help="draft a golden file from a PDF")
    parser.add_argument("--page", type=int, default=14)
    parser.add_argument("--from-run", help="project slug whose run supplies candidate values")
    parser.add_argument("--project")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.generate:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        draft = generate(args.generate, args.page, args.from_run)
        target = GOLDEN_DIR / f"{args.generate.stem}.json"
        target.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        unknown = sorted({f for o in draft["openings"] for f in o["unknown"]})
        confirm = sorted({f for o in draft["openings"] for f in o.get("needs_confirming", [])})
        print(f"wrote {target.relative_to(ROOT).as_posix()} - {len(draft['openings'])} opening(s)")
        if confirm:
            print(f"read by a run, please confirm : {', '.join(confirm)}")
        print(f"nobody found, is the doc silent? : {', '.join(unknown) or 'nothing'}")
        return 0

    slugs = [args.project] if args.project else (
        sorted(p.name for p in (storage_root()).iterdir()
               if (p / "extracted" / "line_items.json").exists())
        if args.all else []
    )
    if not slugs:
        parser.error("give --project, --all, or --generate")

    failed = 0
    for slug in slugs:
        result = score_project(slug)
        if result is not None:
            failed |= _report(slug, result)
    print()
    return failed


if __name__ == "__main__":
    sys.exit(main())
