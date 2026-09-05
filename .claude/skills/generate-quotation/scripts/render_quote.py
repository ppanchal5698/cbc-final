#!/usr/bin/env python3
"""Render the draft quotation from priced line items.

    python render_quote.py <project>
    python render_quote.py --demo

Reads  projects/{project}/priced/line_items.json
       projects/{project}/priced/margin_applied.json  (optional overlay)
Writes projects/{project}/quotation.html

Totals come from the calc-engine server so there is exactly one implementation of
the quote arithmetic in the system.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "mcp-servers"))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from _runtime import load_server  # noqa: E402

calc = load_server("calc-engine")

TEMPLATE_DIR = ROOT / "templates"
BLOCK_ORDER = [
    ("door", "Doors, Frames & Hardware"),
    ("accessories", "Restroom Partitions & Accessories"),
    ("frp", "FRP Wall Panels"),
    ("other", "Other"),
]


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run the pricing phase first")
    return json.loads(path.read_text(encoding="utf-8"))


def build_blocks(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group lines into door / accessories / FRP blocks, each with subtotals."""
    blocks: list[dict[str, Any]] = []
    for key, title in BLOCK_ORDER:
        groups: dict[str, dict[str, Any]] = {}
        for line in lines:
            if (line.get("group_type") or "door") != key:
                continue
            name = line.get("group") or "Ungrouped"
            group = groups.setdefault(
                name,
                {"name": name, "opening_size": line.get("opening_size"), "lines": [], "subtotal": 0.0},
            )
            group["lines"].append(line)
            group["subtotal"] = round(group["subtotal"] + float(line.get("ext_price") or 0), 2)
        if groups:
            block_lines = [line for group in groups.values() for line in group["lines"]]
            blocks.append(
                {"key": key, "title": title, "groups": list(groups.values()), "lines": block_lines}
            )
    return blocks


def render(project: str) -> Path:
    project_dir = ROOT / "projects" / project
    data = _load(project_dir / "priced" / "line_items.json")
    lines = data.get("lines", [])

    overlay_path = project_dir / "priced" / "margin_applied.json"
    if overlay_path.exists():
        overlay = {
            record["line_id"]: record
            for record in _load(overlay_path).get("lines", [])
            if "line_id" in record
        }
        for line in lines:
            patch = overlay.get(line.get("line_id"))
            if patch:
                line.update(
                    {k: patch[k] for k in ("margin", "sale_ea", "ext_price") if k in patch}
                )

    blocks = build_blocks(lines)
    totals = calc.compute_totals(
        [
            {"group": f"{line.get('group_type', 'door')}::{line.get('group')}", "ext_price": line.get("ext_price") or 0}
            for line in lines
        ],
        project_state=data.get("project", {}).get("state"),
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("quotation.html").render(
        quote_number=data.get("quote_number", f"CBC-{date.today():%Y%m%d}-{project[:8].upper()}"),
        quote_date=data.get("quote_date", date.today().isoformat()),
        validity_days=data.get("validity_days", 30),
        project=data.get("project", {"name": project}),
        customer=data.get("customer", {}),
        estimator=data.get("estimator", {}),
        notes=data.get("notes", []),
        blocks=blocks,
        totals=totals,
        flag_count=sum(len(line.get("flags") or []) for line in lines),
    )

    output = project_dir / "quotation.html"
    output.write_text(html, encoding="utf-8")
    return output


def _demo() -> None:
    """Runnable check: grouping and subtotals, which is the only real logic here."""
    lines = [
        {"group": "Door 01", "group_type": "door", "ext_price": 100.0},
        {"group": "Door 01", "group_type": "door", "ext_price": 50.5},
        {"group": "Door 02", "group_type": "door", "ext_price": 25.0},
        {"group": "Restroom", "group_type": "accessories", "ext_price": 10.0},
        {"group": "Kitchen", "group_type": "frp", "ext_price": None},
    ]
    blocks = build_blocks(lines)
    assert [b["key"] for b in blocks] == ["door", "accessories", "frp"], blocks
    doors = blocks[0]["groups"]
    assert doors[0]["subtotal"] == 150.5, doors
    assert doors[1]["subtotal"] == 25.0, doors
    assert blocks[2]["groups"][0]["subtotal"] == 0.0, "unpriced FRP line must not crash the roll-up"
    assert (TEMPLATE_DIR / "quotation.html").exists(), "templates/quotation.html missing"
    print("render_quote demo OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if args.demo:
        _demo()
        return 0
    if not args.project:
        parser.error("a project name is required unless --demo is given")

    output = render(args.project)
    print(f"Draft quotation written to {output}")
    print("Draft ready for estimator review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
