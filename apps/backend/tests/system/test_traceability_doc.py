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

Deliberately *not* checked: artifact paths like `extracted/line_items.json`,
which are relative to a project directory and do not exist in the tree; bare
filenames like `mongo.py`; and package names like `@tailwindcss/postcss`.
Checking those means either a pile of false positives or a pile of exceptions,
and neither catches a broken link.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

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
# Directories whose contents are runtime data, not source. A real install has
# price books and projects in them; a clean checkout does not. The docs should
# still say where those live, so the roots are named here and not descended
# into. Checking them against a developer's disk is what made this test pass
# locally and fail in CI.
RUNTIME_ROOTS = ("data/pricebooks/", "data/projects/", "apps/web/test-results/")

KNOWN_ABSENT = {
    # Gitignored by design - a developer copies the .example beside it. Absent
    # from a clean checkout on purpose, so this is not a defect.
    ".claude/settings.local.json",
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


@lru_cache(maxsize=1)
def _tracked() -> frozenset[str]:
    """Every path git tracks, plus each parent directory.

    The filesystem is the wrong oracle here: it answers about the machine the
    test runs on, so a doc naming a gitignored file passes locally and fails in
    CI. Git's index is the same everywhere.
    """
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths: set[str] = set()
    for line in out.splitlines():
        rel = line.strip()
        if not rel:
            continue
        paths.add(rel)
        parent = Path(rel).parent
        while parent != Path("."):
            paths.add(parent.as_posix())
            parent = parent.parent
    return frozenset(paths)


def _in_repo(base: Path, target: str) -> bool:
    try:
        rel = (base / target).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return False  # a link that climbs out of the repository
    return rel in _tracked()


def _clean(target: str) -> str | None:
    """Strip decoration, or None when this is not a path we check."""
    target = target.split("#", 1)[0].strip()
    target = LINE_SUFFIX.sub("", target)
    if not target or target.startswith(("http://", "https://", "mailto:", "/")):
        return None
    # Globs, ellipses, placeholders, regexes and anything with whitespace are prose.
    if "..." in target or re.search(r"[\s*?{}<>$()\[\]\\\"]", target):
        return None
    if target.rstrip("/").startswith(tuple(r.rstrip("/") for r in RUNTIME_ROOTS)):
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
        if target and target not in KNOWN_ABSENT and not _in_repo(base, target):
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
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout; the tracked-path oracle is unavailable")
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


def test_the_checker_would_catch_a_dangling_path() -> None:
    """The check above is only worth having if it actually fails."""
    docs = ROOT / "docs"
    assert _in_repo(docs, "README.md")
    assert not _in_repo(docs, "nope.md")
    assert _in_repo(ROOT, "docs/pipeline")  # a directory, via its children


def test_prose_is_not_mistaken_for_a_path() -> None:
    """Everything here appears in backticks somewhere and names no file."""
    for token in (
        "rm -rf",              # a command
        "MONGODB_URI",         # an env var
        "save_artifact",       # a tool
        "extracted/line_items.json",  # relative to a project dir, not the repo
        "@tailwindcss/postcss",          # a package
        "data/pricebooks/...",           # an elided example
        "extracted/*.json",              # a glob
        "projects/{project}/",           # a placeholder
    ):
        assert _clean(token) is None or not token.startswith(ROOTED), token


def test_runtime_data_is_not_checked_against_a_developers_disk() -> None:
    """These exist on a real install and in no clean checkout.

    Asserting on them is what made this test green locally and red in CI.
    """
    for token in (
        "data/pricebooks/index.json",
        "data/pricebooks/catalogs/catalog_nudo.md",
        "data/projects/_scratch/",
        "apps/web/test-results/",
    ):
        assert _clean(token) is None, token

    # Seed reference data is tracked, so it stays checked.
    assert _clean("data/reference-library/margins/margin_framework.json")
    assert _in_repo(ROOT, "data/reference-library/margins/margin_framework.json")
