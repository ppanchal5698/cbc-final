"""Apply the three configuration-audit fixes that a run cannot apply itself.

    python scripts/apply_config_audit.py

`.claude` is a PROTECTED_DIR in .claude/hooks/pre_delete_guard.py, and deletion
outside projects/ is blocked by the same hook. Both are correct: those are the
rules a pipeline run operates under, and a run must not be able to edit them or
delete its way around them. So the fixes that touch them are applied from
outside a run, deliberately, by a person - the same route
apply_pageindex_prompts.py took.

Covers fix_plan.md tasks 1, 2 and 4. Idempotent: safe to run twice.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = ROOT / ("." + "claude")

changed: list[str] = []
problems: list[str] = []


# ── Task 1: directories the PageIndex deletion left behind ──────────────────
# Untracked, and holding nothing but __pycache__. They make `ls src/cbc` and
# `ls mcp-servers` contradict CLAUDE.md and .mcp.json, which is how someone ends
# up importing a package that no longer exists.
LEFTOVERS = [
    ROOT / "packages" / "cbc" / "catalog",
    ROOT / "packages" / "cbc" / "documents",
    ROOT / "mcp-servers" / "document-index",
    ROOT / "mcp-servers" / "pricebook",
]

def _force_writable(func, path, _exc):
    """Windows refuses to unlink a read-only file; clear the bit and retry once."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _remove_tree(directory: pathlib.Path) -> str | None:
    """Delete a directory on Windows, where "empty" and "removable" differ.

    The first run of this script unlinked every .pyc in src/cbc/catalog and then
    failed with PermissionError removing the emptied __pycache__ itself. On this
    machine the repo lives under OneDrive, and the sync client (or a virus
    scanner, or an interpreter that just imported from it) can hold a directory
    handle for a moment after its contents are gone. Retrying briefly clears it.
    """
    kwargs = {"onexc": _force_writable} if sys.version_info >= (3, 12) else {"onerror": lambda f, p, e: _force_writable(f, p, e)}
    for attempt in range(5):
        try:
            shutil.rmtree(directory, **kwargs)
            return None
        except (PermissionError, OSError) as exc:
            if not directory.exists():
                return None
            if attempt == 4:
                return f"{directory.relative_to(ROOT)}: {type(exc).__name__} - {exc}"
            time.sleep(0.4 * (attempt + 1))
    return None


for directory in LEFTOVERS:
    if not directory.exists():
        continue
    live = [p for p in directory.rglob("*") if p.is_file() and p.suffix != ".pyc"]
    if live:
        # Refuse rather than delete something real. The audit checked these were
        # empty; if that changed, a person should look.
        problems.append(f"{directory.relative_to(ROOT)} holds {len(live)} non-.pyc file(s) - left alone")
        continue
    failure = _remove_tree(directory)
    if failure:
        # Cosmetic either way, and never a reason to skip the other two tasks -
        # which is exactly what an uncaught exception here did on the first run.
        problems.append(f"could not remove {failure} (retry after closing editors/Python)")
    else:
        changed.append(f"deleted {directory.relative_to(ROOT)}")


# ── Task 2: the catalog skill still promises prices ─────────────────────────
# The catalog tools return a page to open, never a price - mcp-servers/catalog/
# tools.py says so in its first paragraph. The frontmatter still advertised the
# old contract, and the Script block invoked a helper deleted with the FTS index.
skill = CFG / "skills" / "scan-product-catalog" / "SKILL.md"
try:
    body = skill.read_text(encoding="utf-8") if skill.exists() else None
except OSError as exc:
    body = None
    problems.append(f"skills/scan-product-catalog/SKILL.md unreadable: {exc}")

if body is not None:
    before = body

    body = body.replace(
        """  Searches the vendor price-book PDFs (Hager, National Guard, PEMKO/Markar,
  Rockwood, ASI, Bobrick, Bradley, Gamco, World Dryer, NUDO) for a product by
  part number, series or description, and returns list price with page-level
  traceability. Use when a matched item needs a list price before the multiplier
  is applied.""",
        """  Finds which page of which vendor price book carries a part - Hager,
  National Guard, PEMKO/Markar, Rockwood, ASI, Bobrick, Bradley, Gamco, World
  Dryer, NUDO - searching by part number, series or description. Returns the
  page to open and why it matched, not a price: the price is read off the sheet.
  Use when a matched item needs a list price before the multiplier is applied.""",
    )

    body = body.replace(
        """## Script

```bash
python .claude/skills/scan-product-catalog/scripts/search_pricebook.py --list
```

```bash
python .claude/skills/scan-product-catalog/scripts/search_pricebook.py hager 3510 --category locks
```

## Output

Every result carries `source_file`, `source_page`, `effective_date`, the
`multiplier_tier` used and its `multiplier_effective_date` - the full provenance
chain NFR-3 requires.""",
        """## Worked example

There is no script. `search_pricebook.py` was deleted with the extraction index
it queried; the catalog MCP server replaced it, and the price now comes off the
page rather than out of a table nobody checked.

```
mcp__catalog__find_pages(query="3510 lock", vendor="hager")
  -> file_path "pricebooks/hager_price_book_18.pdf", pdf_page 297,
     locator "PDF p297 (printed p23)", has_prices true

mcp__pdf-tools__extract_tables(file_path=..., pages="297")
  -> the row, and the list price on it

mcp__catalog__get_multiplier(vendor="hager", tier="locks")
  -> 0.290, effective 2026-03-02
```

Pass `file_path` and `pdf_page` exactly as `find_pages` returned them. The books
are not under the project's uploads, and a run that guessed that directory found
the right page and could not open it.

## Output

Quote the `locator` verbatim - it carries the PDF page and the number printed on
the page, and they differ on most pages because section numbering restarts. With
the file name, the multiplier tier and its effective date, that is the full
provenance chain NFR-3 requires.""",
    )

    if body != before:
        try:
            skill.write_text(body, encoding="utf-8", newline="\n")
            changed.append("skills/scan-product-catalog/SKILL.md")
        except OSError as exc:
            problems.append(f"skills/scan-product-catalog/SKILL.md not written: {exc}")
elif not skill.exists():
    problems.append("skills/scan-product-catalog/SKILL.md not found")


# ── Task 4: every agent gets a tools allowlist ──────────────────────────────
# None of the ten declared one, so a delegated run handed each subagent the whole
# toolset: takeoff-engineer could reach p21-connector, delivery-agent every write
# tool. toolsets.py scopes per job type, not per agent, so nothing else did.
#
# Written as explicit tool names rather than `mcp__server__*`. Wildcards work in
# settings.json permissions; whether agent frontmatter expands them is not
# something this repo demonstrates anywhere, and a list that silently matched
# nothing would leave a subagent with no MCP tools at all.
PDF = ["mcp__pdf-tools__search_pdf", "mcp__pdf-tools__find_sheets",
       "mcp__pdf-tools__extract_tables", "mcp__pdf-tools__extract_text",
       "mcp__pdf-tools__get_page_image", "mcp__pdf-tools__get_page_size"]
CALC = ["mcp__calc-engine__calculate_line", "mcp__calc-engine__apply_margin",
        "mcp__calc-engine__compute_totals", "mcp__calc-engine__validate_margin"]
STORE = ["mcp__artifact-storage__save_artifact", "mcp__artifact-storage__get_artifact",
         "mcp__artifact-storage__list_versions", "mcp__artifact-storage__list_project_files"]
P21 = ["mcp__p21-connector__lookup_last_po", "mcp__p21-connector__check_freshness",
       "mcp__p21-connector__search_item"]
CATALOG = ["mcp__catalog__list_catalogs", "mcp__catalog__get_catalog_overview",
           "mcp__catalog__find_pages", "mcp__catalog__get_page",
           "mcp__catalog__get_multiplier", "mcp__catalog__get_special_net",
           "mcp__catalog__is_stock_item"]

AGENT_TOOLS: dict[str, list[str]] = {
    # Phase 0/1 - scaffolds the project and records metadata. No PDF parsing.
    "intake-coordinator": ["Read", "Write", "Glob", "Bash", *STORE],
    # Phase 2 - reads spec PDFs.
    "spec-scope-analyst": ["Read", "Write", "Glob", "Grep", *PDF, *STORE],
    # Phase 3 - reads drawings, runs parse_schedule.py.
    "takeoff-engineer": ["Read", "Write", "Glob", "Bash", *PDF, *STORE],
    # Phase 3b - geometry off the drawings.
    "frp-specialist": ["Read", "Write", *PDF, *STORE],
    # Phase 4 - matches against the catalog. Prices nothing, so no calc, no P21.
    "product-matcher": ["Read", "Write", "Glob", "Grep", *CATALOG, *STORE],
    # Phase 4 - the only agent that needs every cost path.
    "pricing-engineer": ["Read", "Write", *CATALOG, *PDF, *CALC, *P21, *STORE],
    # Phase 4/6 - totals an already-priced quote and renders it.
    "quote-builder": ["Read", "Write", "Bash", *CALC, *STORE],
    # Phase 5 - its own body, line 14: "You do not use external tools. You read
    # what the other agents produced and judge it." Taken at its word.
    "quality-reviewer": ["Read", "Glob", "Grep", "Write"],
    # Phase 6 - exports the PDF and writes the draft email. Never sends; the
    # absence of any mail path here is deliberate and matches pre_send_quote.py.
    "delivery-agent": ["Read", "Write", "Bash", *STORE],
    # Runs on upload, outside a bid. Reads a sheet, records what it found.
    "pricebook-ingestor": ["Read", "Write", *CATALOG, *PDF, *STORE],
}

for name, tools in AGENT_TOOLS.items():
    path = CFG / "agents" / f"{name}.md"
    if not path.exists():
        problems.append(f"agents/{name}.md not found")
        continue
    body = path.read_text(encoding="utf-8")
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        problems.append(f"agents/{name}.md does not start with frontmatter")
        continue
    if any(line.startswith("tools:") for line in lines):
        continue  # already applied
    # Insert immediately before the closing --- of the frontmatter.
    try:
        close = lines.index("---", 1)
    except ValueError:
        problems.append(f"agents/{name}.md has no frontmatter close marker")
        continue
    lines.insert(close, "tools: " + ", ".join(tools))
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        changed.append(f"agents/{name}.md (+{len(tools)} tools)")
    except OSError as exc:
        problems.append(f"agents/{name}.md not written: {exc}")


print("changed:" if changed else "nothing to change (already applied)")
for item in changed:
    print("  ", item)
if problems:
    print("\nneeds a look:")
    for item in problems:
        print("  ", item)
sys.exit(1 if problems else 0)
