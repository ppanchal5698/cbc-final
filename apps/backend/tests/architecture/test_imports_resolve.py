"""Every deferred import names something that exists.

`cbc.services.alerts` and `cbc.services.matching_gate` were moved to
`archive/pre-monolith/` while three unguarded call sites kept importing them
inside function bodies - `worker_kit.runtime._dead_letter` (every job failure),
`reap_abandoned` (every reap) and the `match_and_price` branch (every pricing
pass, after the quote had already been committed). A deferred import fails at
call time, not at boot, so nothing noticed: the modules compiled, the app
started, and only a failing job or a priced bid hit the ImportError.

`cbc.core.pdftext` was the same defect one layer out. `mcp-servers/pdf-tools`
imported it, it had been archived too, and so the PDF text-extraction server
could not import at all - which is why `main.py --selftest`, the CI gate, was
red. Hence both trees are scanned here, not just the backend package.

`compileall` cannot catch this and neither can a smoke import: the import is
syntactically fine and sits inside a function nothing calls at start-up. This
catches it by resolving the name every `from <package> import <name>` asks for.

alerts has since moved again, deliberately, into ops' public surface
(`cbc.modules.ops.api.alerts`); the regression check follows it there.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parents[1]

# Both trees import the same `cbc.*` packages and both were importing an
# archived module. mcp-servers' own bare imports (`from tools import TOOLS`,
# resolved by _runtime's sys.path juggling) are ignored: the scan follows only
# the packages named below.
SCAN_ROOTS = (_BACKEND / "src" / "cbc", _REPO / "mcp-servers")

# ponytail: restricted to packages whose __init__ exports nothing, so "the name
# must be a submodule" holds without importing anything. Widen by reading
# __all__ if one of these ever grows real exports.
NAMESPACE_PACKAGES = frozenset(
    {
        "cbc.services",
        "cbc.domain",
        "cbc.core",
        "cbc.pageindex",
        "cbc.http",
        "cbc.persistence",
        # A module's public surface is a package of submodules too, and the
        # worker reaches it through the same deferred imports that hid this defect.
        "cbc.modules.ops.api",
    }
)


def _resolves(dotted: str) -> bool:
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _imports_in(path: Path) -> list[tuple[Path, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        if node.module not in NAMESPACE_PACKAGES:
            continue
        for alias in node.names:
            found.append((path, node.lineno, f"{node.module}.{alias.name}"))
    return found


def _submodule_imports() -> list[tuple[Path, int, str]]:
    """Every `from <namespace package> import <name>` across both trees."""
    found: list[tuple[Path, int, str]] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            found.extend(_imports_in(path))
    return found


def test_namespace_package_imports_all_resolve() -> None:
    imports = _submodule_imports()
    assert imports, "found no imports to check - the scan is broken, not the code"

    missing = [
        f"{path.relative_to(_REPO)}:{line} imports {dotted}"
        for path, line, dotted in imports
        if not _resolves(dotted)
    ]
    assert not missing, "imports that name nothing importable:\n" + "\n".join(missing)


def test_the_three_known_regressions_resolve() -> None:
    """Named explicitly so re-archiving any of these three is unmistakable."""
    for dotted in ("cbc.modules.ops.api.alerts", "cbc.services.matching_gate", "cbc.core.pdftext"):
        assert _resolves(dotted), f"{dotted} is gone again - see this module's docstring"
