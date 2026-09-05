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
)


def _cases():
    cases = []
    for name in SERVERS:
        module = load_server(name)
        tools = {spec["name"]: spec for spec in module.TOOLS}
        for tool_name, handler in module.HANDLERS.items():
            cases.append((name, tool_name, handler, tools[tool_name]))
    return cases


def test_there_are_twenty_six_tools() -> None:
    total = sum(len(load_server(name).HANDLERS) for name in SERVERS)
    assert total == 26


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
