"""Every path a document names must exist.

This used to assert that four specific files were present. That is weaker than
it looks: it says nothing about the hundreds of other paths the docs name, and
it goes red for the wrong reason the moment the doc set is reorganised.
Reorganising it once left roughly fifteen dangling references across CLAUDE.md,
the agent config, a CI comment, a shell script and an agent prompt, and none of
them were caught here.

So the check is the general one now, over the two things that are unambiguously
repository paths:

1. **Markdown links** - `[text](target)` - resolved against the document, the
   way a reader clicks them. This is the class that broke.
2. **Backticked paths rooted at a known top-level directory** - `docs/x.md`,
   `scripts/y.py`. A leading segment we recognise is what makes it a repo path
   rather than prose.

Deliberately *not* checked: artifact paths like `extracted/door_schedule.json`,
which are relative to a project directory and do not exist in the tree; bare
filenames like `mongo.py`; and package names like `@tailwindcss/postcss`.
Checking those means either a pile of false positives or a pile of exceptions,
and neither catches a broken link.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.shared import ROOT

# Where we keep prose worth holding to this standard.
SEARCH_DIRS = ("docs", ".claude", "workflows", "mcp-servers", "infra", "scripts")

# Markdown that is not ours to police.
SKIP_PARTS = {"node_modules", ".next", "_archive", "graphify-out", ".venv", "__pycache__"}

# A backticked token is a repo path when it starts with one of these.
ROOTED = (
    "docs/",
    "apps/",
    ".claude/",
    ".github/",
    "infra/",
    "scripts/",
    "workflows/",
    "mcp-servers/",
    "data/",
    "templates/",
)

# Paths we know are absent, and are tracked as defects rather than hidden.
# Removing an entry here is the right move the moment the file comes back;
# adding one to make this test green without a matching entry in
# docs/data_stewardship.md is the wrong move.
KNOWN_ABSENT = {
    # Gitignored by design - a developer copies the .example beside it. Absent
    # from a clean checkout on purpose, so this is not a defect.
    ".claude/settings.local.json",
    # Three scripts the repository lost. Referenced from agent definitions and
    # workflows, and recorded under "Known defects" in docs/data_stewardship.md.
    "scripts/init_project.sh",
    "scripts/validate_project.py",
    "scripts/export_audit_report.py",
}

BACKTICK = re.compile(r"`([^`\n]+)`")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
LINE_SUFFIX = re.compile(r":\d+(-\d+)?$")


def _markdown_files() -> list[Path]:
    found: list[Path] = []
    for name in SEARCH_DIRS:
        base = ROOT / name
        if base.is_dir():
            found.extend(base.rglob("*.md"))
    found.extend(ROOT.glob("*.md"))
    return sorted(p for p in found if not SKIP_PARTS & set(p.parts))


def _clean(target: str) -> str | None:
    """Strip decoration, or None when this is not a path we check."""
    target = target.split("#", 1)[0].strip()
    target = LINE_SUFFIX.sub("", target)
    if not target or target.startswith(("http://", "https://", "mailto:", "/")):
        return None
    # Globs, placeholders, regexes and anything with whitespace are prose.
    if re.search(r"[\s*?{}<>$()\[\]\\\"]", target):
        return None
    return target


def _missing_in(doc: Path) -> list[str]:
    text = doc.read_text(encoding="utf-8")
    seen: set[str] = set()
    missing: list[str] = []

    def check(raw: str, base: Path) -> None:
        if raw in seen:
            return
        seen.add(raw)
        target = _clean(raw)
        if target and target not in KNOWN_ABSENT and not (base / target).exists():
            missing.append(raw)

    # Links resolve the way a reader clicks them: against the document.
    for raw in MD_LINK.findall(text):
        check(raw, doc.parent)

    # Backticked paths are written from the repository root.
    for raw in BACKTICK.findall(text):
        if raw.startswith(ROOTED):
            check(raw, ROOT)

    return missing


def test_every_path_named_in_a_doc_exists() -> None:
    broken: dict[str, list[str]] = {}
    for doc in _markdown_files():
        missing = _missing_in(doc)
        if missing:
            broken[str(doc.relative_to(ROOT)).replace("\\", "/")] = missing

    assert not broken, "documents name paths that do not exist: " + "; ".join(
        f"{doc} -> {', '.join(paths)}" for doc, paths in sorted(broken.items())
    )


def test_the_doc_set_has_an_index_and_its_entry_points() -> None:
    """The four documents everything else is reached from."""
    for rel in (
        "docs/README.md",
        "docs/system-design.md",
        "docs/pipeline/README.md",
        "docs/collections.mongodb.md",
    ):
        assert (ROOT / rel).is_file(), f"missing entry point: {rel}"


def test_the_checker_would_catch_a_dangling_path(tmp_path: Path) -> None:
    """The check above is only worth having if it actually fails."""
    (tmp_path / "real.md").write_text("ok", encoding="utf-8")
    doc = tmp_path / "sample.md"
    doc.write_text(
        "Link that works: [a](real.md). Link that does not: [b](gone.md).\n"
        "Rooted and real: `docs/README.md`. Rooted and not: `docs/nope.md`.\n"
        "Prose that is not a path: `rm -rf`, `MONGODB_URI`, `mongo.py`,\n"
        "`extracted/door_schedule.json`, `@tailwindcss/postcss`, `api/`.\n",
        encoding="utf-8",
    )
    assert _missing_in(doc) == ["gone.md", "docs/nope.md"]
