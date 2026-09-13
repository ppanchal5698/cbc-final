"""The requirements_traceability.md table must point at real paths."""
from __future__ import annotations

import pytest
import re
from pathlib import Path

from tests.shared import DATA_DOCS, ROOT

DOC = DATA_DOCS / "requirements_traceability.md"
PATH_RE = re.compile(r"`([^`]+)`")


@pytest.mark.xfail(strict=True, reason=(
    "data/docs/requirements_traceability.md still names pre-cutover paths - "
    "packages/cbc/..., services/quoting/api/routers/..., root tests/... - about 50 "
    "of them. The doc is stale; rewrite it once Phase 3 settles the module paths."
))
def test_traceability_paths_exist() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing: list[str] = []
    for match in PATH_RE.finditer(text):
        rel = match.group(1)
        if rel.startswith("FR-") or rel.startswith("NFR-"):
            continue
        if "/" not in rel and not rel.endswith(".py"):
            continue
        # Skip bare package dirs that end with /
        path = ROOT / rel.rstrip("/")
        if not path.exists():
            missing.append(rel)
    assert not missing, f"traceability doc names missing paths: {missing}"


def test_architecture_doc_exists() -> None:
    assert (ROOT / "docs" / "architecture.md").is_file()
    assert (DATA_DOCS / "rollout.md").is_file()
    assert (ROOT / "docs" / "data_model.md").is_file()
