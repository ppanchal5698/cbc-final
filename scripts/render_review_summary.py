#!/usr/bin/env python3
"""Render review/review_summary.html from priced lines and review flags.

    python scripts/render_review_summary.py <project>

Reads  projects/{project}/priced/line_items.json
       projects/{project}/review/review_flags.json  (optional)
Writes projects/{project}/review/review_summary.html
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-servers"))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from _runtime import load_server  # noqa: E402

calc = load_server("calc-engine")
TEMPLATE_DIR = ROOT / "templates"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _confidence_level(confidence: float | None, flags: list[str]) -> str:
    if flags and any("manual" in f.lower() or "missing" in f.lower() for f in flags):
        return "yellow"
    if confidence is None:
        return "yellow"
    if confidence < 0.75:
        return "red"
    if confidence >= 0.9:
        return "green"
    return "yellow"


def _build_lines(priced: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for line in priced.get("lines", []):
        confidence = line.get("confidence")
        flags = list(line.get("flags") or [])
        cost = line.get("cost")
        level = _confidence_level(confidence, flags)
        if cost is None and line.get("cost_source") == "MANUAL":
            level = "red" if level == "green" else level
        status = "MANUAL" if cost is None else "PRICED"
        if flags:
            status = flags[0].replace("_", " ").upper()
        lines.append(
            {
                "line_id": line.get("line_id"),
                "opening": line.get("group"),
                "description": line.get("description", ""),
                "part_number": line.get("part_number") or line.get("part"),
                "vendor": line.get("vendor"),
                "quantity": line.get("quantity", 1),
                "cost": cost,
                "confidence": confidence,
                "level": level,
                "status": status,
                "source_page": line.get("source_page"),
                "price_book_version": line.get("price_book_version"),
                "substitution_note": line.get("substitution_note"),
                "note": line.get("cost_source_detail"),
            }
        )
    return lines


def _summary(lines: list[dict[str, Any]], grand_total: float) -> dict[str, Any]:
    high = sum(1 for line in lines if line["level"] == "red")
    medium = sum(1 for line in lines if line["level"] == "yellow")
    confident = sum(1 for line in lines if line["level"] == "green")
    return {
        "lines": len(lines),
        "high": high,
        "medium": medium,
        "confident": confident,
        "grand_total": grand_total,
    }


def render(project: str) -> Path:
    project_dir = ROOT / "projects" / project
    priced = _load(project_dir / "priced" / "line_items.json")
    if not priced:
        raise FileNotFoundError(f"{project_dir / 'priced' / 'line_items.json'} not found")

    flags_payload = _load(project_dir / "review" / "review_flags.json")
    raw_flags = []
    if isinstance(flags_payload, list):
        raw_flags = flags_payload
        flags_payload = {}
    elif flags_payload:
        raw_flags = flags_payload.get("flags", [])

    normalized_flags = []
    for flag in raw_flags:
        if not isinstance(flag, dict):
            continue
        severity = str(flag.get("severity", "medium")).lower()
        level = "red" if severity == "high" else "yellow" if severity == "medium" else "green"
        normalized_flags.append({**flag, "level": level})

    lines = _build_lines(priced)
    totals = calc.compute_totals(
        [
            {
                "group": line.get("group") or "ungrouped",
                "ext_price": line.get("ext_price"),
                "sale_ea": line.get("sale_ea"),
                "quantity": line.get("quantity", 1),
            }
            for line in priced.get("lines", [])
        ],
        project_state=(priced.get("project") or {}).get("state"),
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("review_summary.html").render(
        project=priced.get("project", {"name": project}),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        summary=_summary(lines, totals.get("grand_total", 0.0)),
        lines=lines,
        flags=normalized_flags,
        blocked_on=(flags_payload or {}).get("blocked_on", []),
        rfis=(flags_payload or {}).get("rfis", []),
        prior_quotes=(flags_payload or {}).get("prior_quotes", []),
    )

    output = project_dir / "review" / "review_summary.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project slug under projects/")
    args = parser.parse_args()
    try:
        output = render(args.project)
    except FileNotFoundError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(f"Review summary written to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
