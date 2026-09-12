"""Parse Claude artifacts through Pydantic and score extraction confidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from cbc.core.paths import repo_root
from cbc.schemas.claude_output import (
    DoorSchedule,
    FrpTakeoff,
    HardwareSets,
    PricedQuote,
    ScopeMetadata,
    ScopeSummary,
)
from cbc.services import storage
from cbc.validation.artifacts import ArtifactValidationError
from cbc.validation.review import CONFIDENCE_FLOOR, REQUIRED_OPENING_FIELDS

ROOT = repo_root()

EXTRACT_REL = (
    ("extracted/door_schedule.json", "door_schedule"),
    ("extracted/scope_metadata.json", "scope_metadata"),
    ("extracted/scope_summary.json", "scope_summary"),
    ("extracted/hardware_sets.json", "hardware_sets"),
    ("extracted/frp_takeoff.json", "frp_takeoff"),
)
PRICE_REL = (("priced/line_items.json", "priced_lines"),)

# Completeness below this (share of openings with all required fields) routes
# to needs-review instead of autopilot pricing.
COMPLETENESS_FLOOR = 0.5
# Sum of qty across openings that is not a real bid set.
ABSURD_QTY_TOTAL = 100_000.0
ABSURD_QTY_EACH = 10_000.0

ReviewVerdict = Literal["ok", "needs_review", "reject"]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_pydantic(exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc") or ())
        out.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return out[:20]


def parse_file(kind: str, raw: Any) -> Any:
    if kind == "door_schedule":
        return DoorSchedule.parse_payload(raw)
    if kind == "scope_metadata":
        return ScopeMetadata.model_validate(raw)
    if kind == "scope_summary":
        return ScopeSummary.model_validate(raw)
    if kind == "hardware_sets":
        if isinstance(raw, list):
            return HardwareSets(sets=raw)
        return HardwareSets.model_validate(raw)
    if kind == "frp_takeoff":
        return FrpTakeoff.model_validate(raw)
    if kind == "priced_lines":
        return PricedQuote.parse_payload(raw)
    raise ValueError(f"unknown Claude artifact kind {kind!r}")


def _project_root(slug: str) -> Path:
    try:
        return storage.project_dir(slug)
    except Exception:
        return ROOT / "projects" / slug


def check_contracts(slug: str, rel_and_kind: tuple[tuple[str, str], ...]) -> tuple[list[str], list[dict[str, Any]]]:
    """Return (problems, quarantine rows) for the named artifacts that exist."""
    root = _project_root(slug)
    problems: list[str] = []
    quarantine: list[dict[str, Any]] = []
    for relative, kind in rel_and_kind:
        path = root / relative
        if not path.is_file():
            continue
        try:
            raw = _load(path)
        except json.JSONDecodeError as exc:
            msg = f"{relative}: not valid JSON ({exc})"
            problems.append(msg)
            quarantine.append(
                {"relPath": relative, "raw": path.read_text(encoding="utf-8", errors="replace")[:200_000], "errors": [msg]}
            )
            continue
        try:
            parsed = parse_file(kind, raw)
        except ValidationError as exc:
            errors = _format_pydantic(exc)
            problems.extend(f"{relative}: {e}" for e in errors)
            quarantine.append({"relPath": relative, "raw": raw, "errors": errors})
            continue
        except (ValueError, TypeError) as exc:
            problems.append(f"{relative}: {exc}")
            quarantine.append({"relPath": relative, "raw": raw, "errors": [str(exc)]})
            continue
        if kind == "door_schedule":
            qty_problems = _absurd_qty(parsed)
            if qty_problems:
                problems.extend(f"{relative}: {p}" for p in qty_problems)
                quarantine.append({"relPath": relative, "raw": raw, "errors": qty_problems})
    return problems, quarantine


def _absurd_qty(schedule: DoorSchedule) -> list[str]:
    problems: list[str] = []
    total = 0.0
    for opening in schedule.openings:
        qty = float(opening.qty or 1)
        if qty > ABSURD_QTY_EACH:
            problems.append(f"opening qty {qty} exceeds {ABSURD_QTY_EACH:g}")
        total += qty
    if total > ABSURD_QTY_TOTAL:
        problems.append(f"total qty {total} exceeds {ABSURD_QTY_TOTAL:g}")
    return problems


def extraction_review_verdict(slug: str) -> ReviewVerdict:
    """ok / needs_review for a parsed door schedule. reject is handled by check_contracts."""
    path = _project_root(slug) / "extracted" / "door_schedule.json"
    if not path.is_file():
        return "ok"
    try:
        raw = _load(path)
        schedule = DoorSchedule.parse_payload(raw)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError):
        return "needs_review"
    openings = schedule.openings
    if not openings:
        return "ok"
    complete = 0
    low_conf = 0
    scored = 0
    for opening in openings:
        data = opening.model_dump()
        if all(data.get(field) not in (None, "", []) for field in REQUIRED_OPENING_FIELDS):
            complete += 1
        conf = opening.confidence
        if isinstance(conf, (int, float)):
            scored += 1
            if conf < CONFIDENCE_FLOOR:
                low_conf += 1
    completeness = complete / len(openings)
    if completeness < COMPLETENESS_FLOOR:
        return "needs_review"
    if scored and (low_conf / scored) >= 0.5:
        return "needs_review"
    return "ok"


def raise_if_invalid(job_type: str, slug: str) -> None:
    """Raise ArtifactValidationError with .quarantine when contracts fail."""
    rels: tuple[tuple[str, str], ...] = ()
    if job_type in ("extract_bid_set", "rerun_extraction", "run_full_pipeline"):
        rels += EXTRACT_REL
    if job_type in ("match_and_price", "run_full_pipeline"):
        rels += PRICE_REL
    if not rels:
        return
    problems, quarantine = check_contracts(slug, rels)
    if not problems:
        return
    detail = "; ".join(problems[:5])
    if len(problems) > 5:
        detail += f" (+{len(problems) - 5} more)"
    error = ArtifactValidationError(
        f"Claude output failed schema validation: {detail}",
        phase="contracts",
    )
    error.quarantine = quarantine
    raise error
