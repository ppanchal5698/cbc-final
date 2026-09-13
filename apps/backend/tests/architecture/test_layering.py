"""Architecture layering rules for the modular monolith.

Forbidden:
- modules.X importing anything of modules.Y except modules.Y.api - a module's
  public surface is the only way in (this rule used to be written the other way
  round, forbidding exactly the imports it should require)
- shared.* importing modules.* (shared kernel must not depend upward)
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "cbc"
MODULES = tuple(
    sorted(p.name for p in (SRC / "modules").iterdir() if (p / "__init__.py").is_file())
)


def _iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        if path.name == "__pycache__":
            continue
        yield path


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_modules_reach_each_other_only_through_api() -> None:
    violations: list[str] = []
    for mod in MODULES:
        mod_root = SRC / "modules" / mod
        for path in _iter_py_files(mod_root):
            for imported in _imported_modules(path):
                for other in MODULES:
                    if other == mod:
                        continue
                    other_root, allowed = f"cbc.modules.{other}", f"cbc.modules.{other}.api"
                    inside = imported == other_root or imported.startswith(other_root + ".")
                    public = imported == allowed or imported.startswith(allowed + ".")
                    if inside and not public:
                        violations.append(f"{path.relative_to(SRC)} imports {imported}")
    assert not violations, "imports past another module's api:\n" + "\n".join(violations)


def test_shared_does_not_import_modules() -> None:
    violations: list[str] = []
    shared_root = SRC / "shared"
    for path in _iter_py_files(shared_root):
        for imported in _imported_modules(path):
            if imported == "cbc.modules" or imported.startswith("cbc.modules."):
                violations.append(f"{path.relative_to(SRC)} imports {imported}")
    assert not violations, "shared upward imports:\n" + "\n".join(violations)


def test_domain_job_map_covers_expected_domains() -> None:
    from cbc.worker.domains import DOMAIN_JOB_TYPES

    assert set(DOMAIN_JOB_TYPES) == {
        "intake",
        "extraction",
        "pricing",
        "quoting",
        "catalog",
    }
