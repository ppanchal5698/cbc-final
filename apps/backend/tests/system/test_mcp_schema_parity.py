"""Every MCP handler parameter is declared on that tool's inputSchema."""
from __future__ import annotations

import inspect

from _runtime import load_server

SERVERS = (
    "pdf-tools",
    "catalog",
    "calc-engine",
    "artifact-storage",
    "p21-connector",
    "reference",
    "bid-docs",
    "catalog-docs",
)


def _cases():
    cases = []
    for name in SERVERS:
        module = load_server(name)
        tools = {spec["name"]: spec for spec in module.TOOLS}
        for tool_name, handler in module.HANDLERS.items():
            cases.append((name, tool_name, handler, tools[tool_name]))
    return cases


def test_the_tool_count_is_what_the_toolsets_budget_for() -> None:
    """Every tool's schema sits in context for a whole run, so the count is a cost.

    catalog gained `recall_match` (FR-13, Tier 0), taking it from 9 to 10.
    artifact-storage gained `propose_patch`, taking it from 4 to 5: whole-file
    authorship of a seeded checkpoint is what made one bad key cost a whole run.
    """
    total = sum(len(load_server(name).HANDLERS) for name in SERVERS)
    # pdf-tools(7)+catalog(10)+calc(6)+artifact(5)+p21(3)+reference(14)+bid-docs(4)+catalog-docs(4)
    assert total == 53


def test_handler_parameters_appear_in_the_schema() -> None:
    for server, tool_name, handler, spec in _cases():
        properties = (spec.get("inputSchema") or {}).get("properties") or {}
        signature = inspect.signature(handler)
        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            assert parameter.name in properties, (
                f"{server}.{tool_name} handler has {parameter.name!r} "
                "but inputSchema.properties does not"
            )
            if parameter.default is inspect.Parameter.empty:
                continue
            if "default" not in properties[parameter.name]:
                continue
            schema_default = properties[parameter.name]["default"]
            assert schema_default == parameter.default, (
                f"{server}.{tool_name}.{parameter.name} schema default "
                f"{schema_default!r} != signature {parameter.default!r}"
            )
