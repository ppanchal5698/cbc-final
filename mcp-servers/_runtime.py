#!/usr/bin/env python3
"""Shared stdio runtime for the five CBC MCP servers.

The MCP Python SDK (2.x) takes handler callables on the Server constructor rather
than decorators. All five CBC servers need the same wiring - a TOOLS list of JSON
schemas plus a name-to-function map - so it lives here once instead of five times.

Each server.py stays pure domain logic and calls:

    from _runtime import serve
    serve("catalog", TOOLS, HANDLERS)
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import mcp.types as types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

Handler = Callable[..., Any]


def dump_payload(payload: Any) -> str:
    """Serialise a tool result for the model. Compact on purpose: indent is tokens."""
    return json.dumps(payload, separators=(",", ":"), default=str)


def load_server(name: str) -> ModuleType:
    """Import one server's module under a unique name.

    All five servers are called server.py and each does `from tools import TOOLS`,
    so a plain `import server` in a process that touches two of them silently
    returns whichever was imported first - with the wrong TOOLS attached. In
    production each server runs in its own process and this never bites, but the
    helper scripts and the test suite import several at once.
    """
    module_name = f"cbc_mcp_{name.replace('-', '_')}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    directory = HERE / name
    server_file = directory / "server.py"
    if not server_file.exists():
        raise FileNotFoundError(f"no such MCP server: {name}")

    saved_tools = sys.modules.pop("tools", None)
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(module_name, server_file)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise ImportError(f"cannot load {server_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.path.remove(str(directory))
        sys.modules.pop("tools", None)
        if saved_tools is not None:
            sys.modules["tools"] = saved_tools
    return module


def _as_tool(spec: dict[str, Any]) -> types.Tool:
    return types.Tool(
        name=spec["name"],
        description=spec.get("description", ""),
        inputSchema=spec.get("inputSchema") or spec.get("input_schema") or {"type": "object"},
    )


def build_server(name: str, tools: list[dict[str, Any]], handlers: dict[str, Handler]) -> Server:
    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_as_tool(t) for t in tools])

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        handler = handlers.get(params.name)
        arguments = dict(params.arguments or {})
        if handler is None:
            payload: Any = {"error": f"Unknown tool: {params.name}"}
            is_error = True
        else:
            try:
                payload = await asyncio.to_thread(handler, **arguments)
                is_error = False
            except Exception as exc:  # surfaced to the agent, never swallowed
                payload = {"error": str(exc), "tool": params.name, "arguments": arguments}
                is_error = True
        text = dump_payload(payload)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            is_error=is_error,
        )

    return Server(name, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def serve(name: str, tools: list[dict[str, Any]], handlers: dict[str, Handler]) -> None:
    """Run the server on stdio, or print a self-test summary with --selftest."""
    if "--selftest" in sys.argv:
        missing = [t["name"] for t in tools if t["name"] not in handlers]
        status = "OK" if not missing else f"MISSING HANDLERS: {missing}"
        print(f"{name} {status} - {len(tools)} tools: {[t['name'] for t in tools]}")
        return

    server = build_server(name, tools, handlers)

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_main())
