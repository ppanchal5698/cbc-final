"""Module boundaries, checked on every run - the rules ARCHITECTURE.md states.

1. A module reaches another module only through its `api` package.
2. Nothing outside a module imports its `features`, `domain` or `infrastructure`:
   not the kernel, the composition roots, the MCP servers or the scripts. (Tests
   may; they test those parts directly.)
3. `shared` imports no module.
4. No module names another module's collection. A module declares what it owns
   in `infrastructure/collections.py`; every other module is checked for those
   names, and no module reads collections through `cbc.db`.
5. A module's remaining imports of the legacy kernel (`cbc.db`)
   are marked `ponytail:` with where they go, so the list can only be worked down.
6. Modules import each other one way only: the graph has no cycle.
7. There is no `services/` package: what it held belongs to a module, or to `shared`.

The old first rule here was the inverse of rule 1 - it forbade the one import the
architecture allows.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "cbc"
BACKEND = SRC.parents[1]
REPO = BACKEND.parents[1]
MODULES = tuple(sorted(p.name for p in (SRC / "modules").iterdir() if (p / "__init__.py").is_file()))
PRIVATE = ("features", "domain", "infrastructure")


def _py(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _imports(path: Path) -> list[tuple[int, str]]:
    """Every dotted name an import statement reaches, with its line."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append((node.lineno, node.module))
            # `from cbc.modules.x import features` reaches past x.api as surely as a dotted import
            found += [(node.lineno, f"{node.module}.{alias.name}") for alias in node.names]
    return found


def _module_of(dotted: str) -> tuple[str, str] | None:
    """('catalog', 'api') for cbc.modules.catalog.api.products; ('catalog', '') for the package."""
    match = re.match(r"cbc\.modules\.([a-z_]+)(?:\.([a-z_]+))?", dotted)
    return (match.group(1), match.group(2) or "") if match else None


def test_modules_reach_each_other_only_through_api() -> None:
    violations = []
    for mod in MODULES:
        for path in _py(SRC / "modules" / mod):
            for line, dotted in _imports(path):
                target = _module_of(dotted)
                if target and target[0] != mod and target[0] in MODULES and target[1] != "api":
                    violations.append(f"{path.relative_to(SRC)}:{line} imports {dotted}")
    assert not violations, "imports past another module's api:\n" + "\n".join(sorted(set(violations)))


def test_nothing_outside_a_module_imports_its_insides() -> None:
    outside = [p for p in _py(SRC) if SRC / "modules" not in p.parents]
    outside += _py(REPO / "mcp-servers") + _py(BACKEND / "scripts")
    violations = []
    for path in outside:
        for line, dotted in _imports(path):
            target = _module_of(dotted)
            if target and target[1] in PRIVATE:
                violations.append(f"{path.relative_to(REPO)}:{line} imports {dotted}")
    assert not violations, "imports of a module's private parts:\n" + "\n".join(sorted(set(violations)))


def test_shared_does_not_import_modules() -> None:
    violations = [
        f"{path.relative_to(SRC)}:{line} imports {dotted}"
        for path in _py(SRC / "shared")
        for line, dotted in _imports(path)
        if dotted == "cbc.modules" or dotted.startswith("cbc.modules.")
    ]
    assert not violations, "shared upward imports:\n" + "\n".join(violations)


def _owned_constants() -> dict[str, str]:
    """names.X constant -> the module whose collections.py declares it."""
    owner: dict[str, str] = {}
    for mod in MODULES:
        path = SRC / "modules" / mod / "infrastructure" / "collections.py"
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "names":
                assert owner.setdefault(node.attr, mod) == mod, f"{node.attr} declared by {owner[node.attr]} and {mod}"
    return owner


def test_no_module_names_another_modules_collection() -> None:
    from cbc.persistence import names

    owner = _owned_constants()
    assert owner, "found no declared collections - the scan is broken, not the code"
    stored = {getattr(names, const): mod for const, mod in owner.items()}
    violations = []
    for mod in MODULES:
        for path in _py(SRC / "modules" / mod):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                at = f"{path.relative_to(SRC)}:{getattr(node, 'lineno', '?')}"
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "names":
                    if owner.get(node.attr, mod) != mod:
                        violations.append(f"{at} names {owner[node.attr]}'s names.{node.attr}")
                elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                    if stored.get(node.slice.value, mod) != mod:
                        violations.append(f"{at} indexes {stored[node.slice.value]}'s collection {node.slice.value!r}")
                elif isinstance(node, ast.ImportFrom) and node.module == "cbc.db":
                    reached = {alias.name for alias in node.names} - {"readonly_uri"}
                    if reached:
                        violations.append(f"{at} reads collections through cbc.db ({', '.join(sorted(reached))})")
    assert not violations, "cross-module collection access:\n" + "\n".join(violations)


def test_legacy_kernel_imports_in_modules_are_marked() -> None:
    unmarked = []
    for mod in MODULES:
        for path in _py(SRC / "modules" / mod):
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if re.match(r"\s*(from|import) cbc\.db\b", line) and "ponytail" not in line and (
                    i == 0 or "ponytail" not in lines[i - 1]
                ):
                    unmarked.append(f"{path.relative_to(SRC)}:{i + 1}: {line.strip()}")
    assert not unmarked, "legacy-kernel imports without a ponytail marker:\n" + "\n".join(unmarked)


def test_domain_job_map_covers_expected_domains() -> None:
    from cbc.modules.ops.features.WorkerLoop import DOMAIN_JOB_TYPES

    assert set(DOMAIN_JOB_TYPES) == {
        "intake",
        "extraction",
        "pricing",
        "quoting",
        "catalog",
    }


def test_the_module_graph_has_no_cycles() -> None:
    """A job slice placed in a module that cannot see what it writes is how a cycle starts."""
    edges: dict[str, set[str]] = {mod: set() for mod in MODULES}
    for mod in MODULES:
        for path in _py(SRC / "modules" / mod):
            for _, dotted in _imports(path):
                target = _module_of(dotted)
                if target and target[0] != mod and target[0] in MODULES:
                    edges[mod].add(target[0])

    def cycle(node: str, trail: list[str]) -> list[str] | None:
        if node in trail:
            return trail[trail.index(node):] + [node]
        return next((found for nxt in sorted(edges[node]) if (found := cycle(nxt, trail + [node]))), None)

    cycles = [found for mod in MODULES if (found := cycle(mod, []))]
    assert not cycles, "modules import each other in a circle: " + " -> ".join(cycles[0])


def test_the_services_kernel_is_gone() -> None:
    """A new file there would be the old habit back: give it to the module that owns it."""
    assert not (SRC / "services").exists()
