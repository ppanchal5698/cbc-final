"""Dependency direction for the domain-bounded layout.

    services/*  ──→  packages/cbc  ──→  (nothing above)
    packages/cbc never imports services.*

Cross-service Python imports are also forbidden.
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
    "packages/cbc/core/toolsets.py": ["cbc.db"],
    # calc used to read the seed JSON off disk. Bands, tax and lite-kit prices
    # are Mongo-backed now, so the arithmetic asks the reference service for
    # them - lazily, inside the functions, with DEFAULT_* still the fallback
    # when the lookup fails. Recorded rather than silently allowed.
    "packages/cbc/core/calc.py": ["cbc.services"],
}


def test_the_kernel_imports_nothing_above_itself() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _files("cbc.core"):
        relative = path.relative_to(ROOT).as_posix()
        hits = sorted(
            module
            for module in _imported_roots(path)
            if module.startswith("cbc.") and not module.startswith("cbc.core")
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
