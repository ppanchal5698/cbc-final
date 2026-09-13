"""Ports that hand another module a stored document say what it holds.

The plan: every port returns a typed DTO, never a raw Mongo document. These are
TypedDicts over the stored documents - runtime is unchanged, a reader still gets
the whole document - so what this holds is the contract: each document port names
its type, and no module reads a field from a bid, job, product or opening that the
owning module's type does not declare.
"""
from __future__ import annotations

import ast
import re
import typing
from pathlib import Path

import pytest

from cbc.modules.catalog.api.products import ProductRef
from cbc.modules.extraction.api.openings import OpeningRef
from cbc.modules.ops.api.jobs import JobRef
from cbc.modules.pricing.api.pricing import QuoteTotals
from cbc.modules.projects.api.lookup import ProjectRef

MODULES = Path(__file__).resolve().parents[2] / "src" / "cbc" / "modules"
CBC = MODULES.parent

PORTS = {
    "projects/api/lookup.py": {"load": "ProjectRef", "get": "ProjectRef | None"},
    "ops/api/jobs.py": {"extend_queued_coalesce": "JobRef | None", "enqueue": "JobRef", "latest_for_project": "JobRef | None", "active_pipeline_job": "JobRef | None", "enqueue_exclusive": "JobRef", "active_for_project": "JobRef | None", "reserve": "JobRef | None", "enqueue_pipeline": "JobRef", "active_by_project": "dict[Any, JobRef]", "get": "JobRef | None", "previous_phase_state": "JobRef | None"},
    "catalog/api/products.py": {"get": "ProductRef | None", "by_part": "list[ProductRef]"},
    "extraction/api/openings.py": {"list_for_project": "list[OpeningRef]"},
    "quoting/api/lines.py": {"list_for_project": "list[EstimateLineRef]"},
    "pricing/api/pricing.py": {"totals": "QuoteTotals"},
    "quoting/api/quote.py": {"totals_for": "tuple[pricing.QuoteTotals, list[dict[str, Any]]]", "persist": "pricing.QuoteTotals"},
}


@pytest.mark.parametrize("path", sorted(PORTS))
def test_each_document_port_names_its_type(path: str) -> None:
    tree = ast.parse((MODULES / path).read_text(encoding="utf-8"))
    returns = {n.name: ast.unparse(n.returns) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {name: returns.get(name) for name in PORTS[path]} == PORTS[path]


def test_the_annotations_resolve() -> None:
    import importlib

    for path, functions in PORTS.items():
        module = importlib.import_module("cbc.modules." + path.removesuffix(".py").replace("/", "."))
        for name in functions:
            typing.get_type_hints(getattr(module, name))


# What a module calls a port's result, and the type that port declares.
READERS = {"project": (ProjectRef, "projects"), "job": (JobRef, "ops"), "product": (ProductRef, "catalog"), "opening": (OpeningRef, "extraction")}
READ = re.compile(r"\b(project|job|product|opening)(?:\[\"(\w+)\"\]|\.get\(\"(\w+)\"\))")


def test_no_module_reads_a_field_its_port_does_not_declare() -> None:
    """shared/ is skipped: its `opening["bbox"]` is an artifact row, not a stored opening."""
    undeclared = set()
    for path in CBC.rglob("*.py"):
        rel = path.relative_to(CBC).as_posix()
        if "__pycache__" in rel or rel.startswith("shared/"):
            continue
        here = rel.split("/")[1] if rel.startswith("modules/") else rel.split("/")[0]
        for var, bracket, get in READ.findall(path.read_text(encoding="utf-8")):
            dto, owner = READERS[var]
            field = bracket or get
            if here != owner and field not in dto.__annotations__:
                undeclared.add(f"{rel}: {var}[{field!r}] is not on {dto.__name__}")
    assert not undeclared, "declare the field on the port's type:\n" + "\n".join(sorted(undeclared))


def test_quote_totals_names_every_key_totals_returns() -> None:
    tree = ast.parse((MODULES / "pricing/api/pricing.py").read_text(encoding="utf-8"))
    totals = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "totals")
    returned = next(n.value for n in ast.walk(totals) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    assert {k.value for k in returned.keys} == set(QuoteTotals.__annotations__)
