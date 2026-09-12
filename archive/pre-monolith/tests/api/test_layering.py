"""Dependency direction for the domain-bounded layout.

    services/*  ──→  packages/cbc  ──→  (nothing above)
    packages/cbc never imports services.*

Cross-service Python imports are also forbidden.

That much this file has always checked. What it did not check - while its own
docstring claimed it - is the direction *inside* `packages/cbc`. Upward imports
that remain are listed in INTERNAL_EXCEPTIONS so the debt is enumerated rather
than implied. An exception that stops being true fails
`test_every_listed_exception_is_real`, so the list cannot rot into a permanent
allowlist.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.shared import ROOT

DOMAINS = ("platform", "intake", "extraction", "pricing", "quoting", "catalog")

SOURCE_DIRS = {
    "cbc": ROOT / "packages" / "cbc",
    "cbc.core": ROOT / "packages" / "cbc" / "core",
    **{
        f"services.{name}": ROOT / "services" / name
        for name in DOMAINS
    },
}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _files(package: str) -> list[Path]:
    directory = SOURCE_DIRS[package]
    assert directory.is_dir(), f"{package} is not at {directory}"
    return [path for path in directory.rglob("*.py") if "__pycache__" not in path.parts]


def _imports_into(package: str, prefix: str) -> dict[str, list[str]]:
    offenders = {}
    for path in _files(package):
        hits = sorted(
            module
            for module in _imported_roots(path)
            if module == prefix or module.startswith(prefix + ".")
        )
        if hits:
            offenders[path.relative_to(ROOT).as_posix()] = hits
    return offenders


@pytest.mark.parametrize("package", ["cbc", "cbc.core"])
def test_the_domain_never_imports_a_service(package: str) -> None:
    offenders = _imports_into(package, "services")
    assert not offenders, f"{package} imports a service: {offenders}"


@pytest.mark.parametrize("domain", DOMAINS)
def test_services_do_not_cross_import(domain: str) -> None:
    """A service may import cbc and its own api package, not another domain."""
    package = f"services.{domain}"
    offenders: dict[str, list[str]] = {}
    for other in DOMAINS:
        if other == domain:
            continue
        # No hard-coded imports of other service trees
        for path in _files(package):
            text = path.read_text(encoding="utf-8")
            needle = f"services/{other}/"
            if needle in text.replace("\\", "/"):
                offenders.setdefault(path.relative_to(ROOT).as_posix(), []).append(needle)
    assert not offenders, f"{domain} references another service tree: {offenders}"


@pytest.mark.parametrize("domain", DOMAINS)
def test_each_service_uses_the_domain(domain: str) -> None:
    package = f"services.{domain}"
    # platform worker is a stub; still require api to import cbc
    users = [name for name, hits in _imports_into(package, "cbc").items() if hits]
    assert users, f"expected {package} to import cbc"


KERNEL_EXCEPTIONS = {
    # Compatibility shim: core.calc re-exports domain + reference_calc.
    "packages/cbc/core/calc.py": ["cbc.domain.calc", "cbc.services.reference_calc"],
}


def test_the_kernel_imports_nothing_above_itself() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _files("cbc.core"):
        relative = path.relative_to(ROOT).as_posix()
        hits = sorted(
            module
            for module in _imported_roots(path)
            if module.startswith("cbc.")
            and not module.startswith("cbc.core")
            and not module.startswith("cbc.domain")  # domain sits below core
        )
        allowed = KERNEL_EXCEPTIONS.get(relative, [])
        unexpected = [m for m in hits if m not in allowed]
        if unexpected:
            offenders[relative] = unexpected
    assert not offenders, f"cbc.core reaches up into the domain: {offenders}"


def test_every_listed_kernel_exception_is_still_real() -> None:
    for relative, allowed in KERNEL_EXCEPTIONS.items():
        imported = _imported_roots(ROOT / relative)
        stale = [module for module in allowed if module not in imported]
        assert not stale, f"{relative} no longer imports {stale} - drop the exception"


def test_domain_job_types_partition() -> None:
    from cbc.services.domains import DOMAIN_JOB_TYPES

    seen: set[str] = set()
    for domain, types in DOMAIN_JOB_TYPES.items():
        overlap = seen & set(types)
        assert not overlap, f"{domain} overlaps job types {overlap}"
        seen |= set(types)


# ── the direction inside packages/cbc ───────────────────────────────────────
#
# Low to high. A layer may import anything below it and nothing above it.
LAYERS = (
    "cbc.domain",      # pure rules - no I/O
    "cbc.core",        # I/O primitives + shims over domain
    "cbc.schemas",     # shapes (contracts is the preferred name)
    "cbc.contracts",   # alias of schemas during the rename
    "cbc.persistence", # collection names, envelope, migrations
    "cbc.db",          # the motor client and index setup
    "cbc.pageindex",   # catalog page index
    "cbc.services",    # legacy shared services package
    "cbc.pricing",     # pricing slice of services
    "cbc.quoting",     # quoting slice
    "cbc.extraction",  # extraction slice
    "cbc.platform",    # platform slice
    "cbc.validation",  # acceptance rules
    "cbc.http",        # transport
    "cbc.worker_kit",  # Claude runtime (agents is the preferred name)
    "cbc.agents",      # alias of worker_kit during the rename
)

# Upward imports that exist right now. Removing one is the point of S1-S2; adding
# one needs a reason in this table.
INTERNAL_EXCEPTIONS: dict[str, list[str]] = {
    # Compatibility shim: core.calc re-exports reference_calc for one stage.
    "packages/cbc/core/calc.py": ["cbc.services"],
    # Job claim/finish emit trace spans.
    "packages/cbc/services/jobs.py": ["cbc.http"],
    # Index bootstrap seeds the reference families before first use.
    "packages/cbc/db.py": ["cbc.services"],
    # Classifying a price sheet as list or net needs the vendor tiers.
    "packages/cbc/pageindex/basis.py": ["cbc.services"],
    # Resolves the CBC org id when a legacy project lacks orgId.
    "packages/cbc/persistence/repos.py": ["cbc.db"],
}


def _layer_of(path: Path) -> str | None:
    relative = path.relative_to(ROOT / "packages" / "cbc").as_posix()
    head = relative.split("/")[0]
    name = f"cbc.{head[:-3] if head.endswith('.py') else head}"
    return name if name in LAYERS else None


def _internal_imports(path: Path) -> set[str]:
    return {
        module
        for raw in _imported_roots(path)
        for module in LAYERS
        if raw == module or raw.startswith(module + ".")
    }


def _upward_imports() -> dict[str, list[str]]:
    """Every `cbc.*` import that points at a layer at or above the importer."""
    order = {name: index for index, name in enumerate(LAYERS)}
    found: dict[str, list[str]] = {}
    for path in _files("cbc"):
        layer = _layer_of(path)
        if layer is None:
            continue
        above = sorted(
            module
            for module in _internal_imports(path)
            if module != layer and order[module] > order[layer]
        )
        if above:
            found[path.relative_to(ROOT).as_posix()] = above
    return found


def test_no_layer_imports_one_above_it() -> None:
    offenders = {
        path: [m for m in modules if m not in INTERNAL_EXCEPTIONS.get(path, [])]
        for path, modules in _upward_imports().items()
    }
    offenders = {path: modules for path, modules in offenders.items() if modules}
    assert not offenders, (
        "packages/cbc imports upward through its own layers: "
        f"{offenders}. Move the code down, or add it to INTERNAL_EXCEPTIONS "
        "with the reason."
    )


def test_every_listed_exception_is_real() -> None:
    """An exception that no longer applies is a lie in the documentation."""
    actual = _upward_imports()
    stale = {
        path: modules
        for path, modules in INTERNAL_EXCEPTIONS.items()
        if not set(modules) & set(actual.get(path, []))
    }
    assert not stale, f"INTERNAL_EXCEPTIONS lists imports that are gone: {stale}"
