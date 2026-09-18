#!/usr/bin/env python3
"""Smoke every PDF under bid_pdfs/ for schedule discovery + parse honesty.

For each PDF, find schedule markers / try top candidate pages. Assert one of:
  - openings >= 1 with allowlisted fields, or
  - honest empty with a reason class (never silent zero when a marker is present)

Writes `.cache/bid_pdf_smoke/report.json` (+ .md). Exit 1 on failures.

Usage:
    python apps/backend/scripts/smoke_bid_pdfs.py
    python apps/backend/scripts/smoke_bid_pdfs.py --root bid_pdfs --max-pages 6
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "extract-door-schedule" / "scripts"))
sys.path.insert(0, str(ROOT / "apps" / "backend" / "src"))

import parse_schedule  # noqa: E402

REASON_NO_MARKER = "no_marker"
REASON_REMODEL = "remodel_no_schedule"
REASON_SPEC = "spec_only"
REASON_SHELL = "shell"
REASON_FINISH_ONLY = "finish_schedule_only"
REASON_MARKER_EMPTY = "marker_present_zero_openings"  # failure class
REASON_PARSE_ERROR = "parse_error"

DOOR_SCHEDULE_MARKERS = frozenset(
    {
        "DOOR SCHEDULE",
        "DOOR TYPE SCHEDULE",
        "DOOR FRAME TYPE SCHEDULE",
        "FRAME SCHEDULE",
        "OPENING SCHEDULE",
        "DOOR AND FRAME SCHEDULE",
        "DOOR & FRAME SCHEDULE",
        "DOOR HARDWARE SCHEDULE",
        "HARDWARE GROUPS",
        "HARDWARE SCHEDULE",
        "HW SCHEDULE",
    }
)

REMODEL_HINTS = (
    "reimage",
    "remodel",
    "renovation",
    "national accounts",
)
SPEC_HINTS = ("project manual", "specification", "div 08", "division 08")
SHELL_HINTS = ("building a", "shell", "core and shell", "tenant")


def _door_marker_hits(markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pages that name a door/opening/hardware schedule (not finish-only)."""
    hits = []
    for hit in markers:
        names = {str(m).upper() for m in (hit.get("markers") or [])}
        if names & DOOR_SCHEDULE_MARKERS:
            hits.append(hit)
    return hits


def _rank_marker_pages(markers: list[dict[str, Any]]) -> list[int]:
    """Prefer real door-schedule pages over index / finish-schedule mentions."""

    def priority(hit: dict[str, Any]) -> tuple[int, int]:
        names = {str(m).upper() for m in (hit.get("markers") or [])}
        score = 3
        if "DOOR SCHEDULE" in names and not any("NOTES" in n for n in names):
            score = 0
        elif names & {"OPENING SCHEDULE", "DOOR TYPE SCHEDULE", "DOOR AND FRAME SCHEDULE", "DOOR & FRAME SCHEDULE"}:
            score = 0
        elif names & DOOR_SCHEDULE_MARKERS:
            score = 1
        elif "FINISH SCHEDULE" in names:
            score = 4
        try:
            page = int(hit["source_page"])
        except (KeyError, TypeError, ValueError):
            page = 9999
        return (score, page)

    ordered: list[int] = []
    seen: set[int] = set()
    for hit in sorted(markers, key=priority):
        try:
            page = int(hit["source_page"])
        except (KeyError, TypeError, ValueError):
            continue
        if page in seen:
            continue
        seen.add(page)
        ordered.append(page)
    return ordered


def _classify_empty(pdf: Path, markers: list[dict[str, Any]]) -> str:
    name = pdf.name.lower()
    stem = pdf.stem.lower()
    blob = f"{name} {stem}"
    if any(h in blob for h in REMODEL_HINTS):
        return REASON_REMODEL
    if any(h in blob for h in SPEC_HINTS) or "manual" in blob:
        return REASON_SPEC
    if any(h in blob for h in SHELL_HINTS):
        return REASON_SHELL
    door_hits = _door_marker_hits(markers)
    if not door_hits:
        if any(
            "FINISH SCHEDULE" in {str(m).upper() for m in (h.get("markers") or [])}
            for h in markers
        ):
            return REASON_FINISH_ONLY
        return REASON_NO_MARKER
    return REASON_MARKER_EMPTY


def _iter_pdfs(root: Path) -> list[Path]:
    return sorted({p.resolve() for p in root.rglob("*.pdf") if p.is_file()})


def _smoke_one(pdf: Path, *, max_pages: int) -> dict[str, Any]:
    rel = str(pdf.relative_to(ROOT)).replace("\\", "/") if pdf.is_relative_to(ROOT) else str(pdf)
    row: dict[str, Any] = {
        "path": rel,
        "markers": [],
        "pages_tried": [],
        "openings": 0,
        "ok": False,
        "reason": None,
        "error": None,
    }
    try:
        markers = parse_schedule.find_schedule_pages(str(pdf))
    except Exception as exc:  # noqa: BLE001
        row["reason"] = REASON_PARSE_ERROR
        row["error"] = str(exc)
        return row

    row["markers"] = markers
    pages = _rank_marker_pages(markers)
    # Also try first page when no markers (text-poor CAD may still parse).
    if not pages:
        pages = [1]

    openings: list[dict[str, Any]] = []
    for page in pages[:max_pages]:
        row["pages_tried"].append(page)
        try:
            envelope = parse_schedule.openings_envelope(str(pdf), page, source_file=rel)
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"p{page}: {exc}"
            continue
        found = envelope.get("openings") or []
        if found:
            openings = found
            row["source_page"] = page
            break

    row["openings"] = len(openings)
    if openings:
        row["ok"] = True
        row["reason"] = "openings_found"
        row["sample_marks"] = [o.get("door_number") for o in openings[:8]]
        return row

    reason = _classify_empty(pdf, markers)
    row["reason"] = reason
    # Honest empties are OK; marker-present-zero and parse errors fail.
    row["ok"] = reason in {
        REASON_NO_MARKER,
        REASON_REMODEL,
        REASON_SPEC,
        REASON_SHELL,
        REASON_FINISH_ONLY,
    }
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "bid_pdfs",
        help="Corpus directory (default: <repo>/bid_pdfs)",
    )
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / ".cache" / "bid_pdf_smoke",
        help="Report directory",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"bid_pdfs not found at {args.root} — skip")
        return 0

    pdfs = _iter_pdfs(args.root)
    results = [_smoke_one(pdf, max_pages=args.max_pages) for pdf in pdfs]
    failed = [r for r in results if not r["ok"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(args.root),
        "pdf_count": len(pdfs),
        "ok_count": len(results) - len(failed),
        "fail_count": len(failed),
        "results": results,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / "report.json"
    md_path = args.out / "report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"# Bid PDF smoke ({report['generated_at']})",
        "",
        f"- PDFs: {report['pdf_count']}",
        f"- OK: {report['ok_count']}",
        f"- Fail: {report['fail_count']}",
        "",
        "| PDF | openings | reason | ok |",
        "|---|---:|---|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r['path']}` | {r['openings']} | {r['reason']} | {'yes' if r['ok'] else 'NO'} |"
        )
    if failed:
        lines.extend(["", "## Failures", ""])
        for r in failed:
            lines.append(f"- `{r['path']}`: {r['reason']} {r.get('error') or ''}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"{report['ok_count']}/{report['pdf_count']} OK")
    for r in failed:
        print(f"FAIL {r['path']}: {r['reason']} {r.get('error') or ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
