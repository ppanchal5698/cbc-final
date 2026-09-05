#!/usr/bin/env python3
"""Render an audit report from a project's append-only tool log (NFR-3).

    python scripts/export_audit_report.py <project>
    python scripts/export_audit_report.py <project> --out report.html
    python scripts/export_audit_report.py --demo

Reads  projects/{project}/audit_trail.jsonl
Also folds in cost-source provenance from priced/line_items.json when present, so
the report answers the question an estimator actually asks months later:
"where did this number come from?"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Audit trail - {project}</title>
<style>
 body{{font:13px/1.5 "Segoe UI",Arial,sans-serif;margin:0;padding:28px;color:#1a1a1a}}
 .sheet{{max-width:1100px;margin:0 auto}}
 h1{{font-size:20px;margin:0 0 4px;border-bottom:3px solid #0f3d2e;padding-bottom:10px}}
 h2{{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:#5b6169;margin:26px 0 8px}}
 table{{width:100%;border-collapse:collapse}}
 th{{text-align:left;font-size:11px;text-transform:uppercase;color:#5b6169;
     border-bottom:1px solid #d6d9de;padding:6px 8px}}
 td{{padding:6px 8px;border-bottom:1px solid #d6d9de;vertical-align:top}}
 code{{font-family:Consolas,monospace;font-size:12px;word-break:break-all}}
 .counts{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}}
 .c{{border:1px solid #d6d9de;border-radius:6px;padding:10px 14px;min-width:110px}}
 .c b{{display:block;font-size:20px}}
 .c span{{font-size:11px;color:#5b6169;text-transform:uppercase}}
 .empty{{padding:16px;background:#fff6e0;border:1px solid #8a6100;color:#8a6100;border-radius:6px}}
</style></head><body><div class="sheet">
<h1>Audit trail - {project}</h1>
<div class="counts">{counts}</div>
{sources}
<h2>Tool calls ({total})</h2>
{table}
</div></body></html>
"""


def load_trail(project: str) -> list[dict[str, Any]]:
    path = ROOT / "projects" / project / "audit_trail.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"timestamp": None, "tool_name": "UNPARSEABLE", "tool_input_summary": line[:200]})
    return records


def cost_sources(project: str) -> list[dict[str, Any]]:
    path = ROOT / "projects" / project / "priced" / "line_items.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("lines", [])


def _counts_html(records: list[dict[str, Any]]) -> str:
    tools = Counter(r.get("tool_name") or "unknown" for r in records)
    agents = Counter(r.get("agent_name") or "unknown" for r in records)
    cells = [
        f'<div class="c"><b>{len(records)}</b><span>Tool calls</span></div>',
        f'<div class="c"><b>{len(tools)}</b><span>Distinct tools</span></div>',
        f'<div class="c"><b>{len(agents)}</b><span>Agents</span></div>',
    ]
    return "".join(cells)


def _sources_html(lines: list[dict[str, Any]]) -> str:
    if not lines:
        return ""
    rows = "".join(
        "<tr><td>{desc}</td><td><code>{src}</code></td><td>{detail}</td><td>{book}</td><td>{page}</td></tr>".format(
            desc=escape(str(line.get("description", ""))),
            src=escape(str(line.get("cost_source", "-"))),
            detail=escape(str(line.get("cost_source_detail", "-"))),
            book=escape(str(line.get("price_book_version", "-"))),
            page=escape(str(line.get("source_page", "-"))),
        )
        for line in lines
    )
    return (
        f"<h2>Cost provenance ({len(lines)} lines)</h2><table><thead><tr>"
        "<th>Line</th><th>Cost source</th><th>Detail</th><th>Price book</th><th>Page</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def build_report(project: str) -> str:
    records = load_trail(project)
    if records:
        rows = "".join(
            "<tr><td>{ts}</td><td>{tool}</td><td>{agent}</td><td><code>{summary}</code></td></tr>".format(
                ts=escape(str(r.get("timestamp") or "-")),
                tool=escape(str(r.get("tool_name") or "-")),
                agent=escape(str(r.get("agent_name") or "-")),
                summary=escape(str(r.get("tool_input_summary") or "")),
            )
            for r in records
        )
        table = (
            "<table><thead><tr><th style='width:22%'>Timestamp</th>"
            "<th style='width:16%'>Tool</th><th style='width:14%'>Agent</th>"
            f"<th>Input</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        table = '<div class="empty">No tool calls logged yet for this project.</div>'

    return PAGE.format(
        project=escape(project),
        counts=_counts_html(records),
        sources=_sources_html(cost_sources(project)),
        total=len(records),
        table=table,
    )


def _demo() -> None:
    """Runnable check: malformed lines must not break the report."""
    project_dir = ROOT / "projects" / "_audit_demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    trail = project_dir / "audit_trail.jsonl"
    try:
        trail.write_text(
            '{"timestamp":"2026-08-26T12:00:00Z","tool_name":"Write","agent_name":"takeoff-engineer",'
            '"tool_input_summary":"file_path=extracted/door_schedule.json"}\n'
            "not json at all\n",
            encoding="utf-8",
        )
        records = load_trail("_audit_demo")
        assert len(records) == 2, records
        assert records[1]["tool_name"] == "UNPARSEABLE"
        html = build_report("_audit_demo")
        assert "takeoff-engineer" in html and "Tool calls" in html
        assert build_report("_nonexistent_project").count("No tool calls logged") == 1
    finally:
        import shutil

        shutil.rmtree(project_dir, ignore_errors=True)
    print("export_audit_report demo OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?")
    parser.add_argument("--out", help="Output path (default projects/{project}/audit_report.html)")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if args.demo:
        _demo()
        return 0
    if not args.project:
        parser.error("a project name is required unless --demo is given")

    output = Path(args.out) if args.out else ROOT / "projects" / args.project / "audit_report.html"
    output.write_text(build_report(args.project), encoding="utf-8")
    print(f"Audit report written to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
