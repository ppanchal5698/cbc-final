"""Every MCP tool an agent, command or skill names is one that agent actually has.

The .claude audit found agents told - by their own skill - to call tools missing
from their `tools:` list (parse_door_openings, the catalog-docs search, a special
margin lookup), and an example passing `tier=` to a tool whose argument is
`category`. Each is a turn spent on a refusal, or a quiet fallback. This checks:

1. every `mcp__server__tool` named in a file exists on that server;
2. it is in the `tools:` list of every agent that reads the file - an agent's own
   file, the skills it follows, the commands that run it;
3. every `name=` argument in an example call exists on the tool's schema.
"""
from __future__ import annotations

import importlib.util
import re
from functools import lru_cache
from pathlib import Path

import pytest

from tests.shared import ROOT

CLAUDE = ROOT / ".claude"
TOOL_REF = re.compile(r"mcp__([a-z0-9-]+)__([a-z_]+)")
CALL = re.compile(r"mcp__([a-z0-9-]+)__([a-z_]+)\(([^)]*)\)")
ARG = re.compile(r"(?:^|,)\s*([a-z_]+)\s*=")


@lru_cache(maxsize=None)
def _schemas() -> dict[str, set[str]]:
    """`mcp__server__tool` -> its argument names, from each server's tools.py."""
    found: dict[str, set[str]] = {}
    for tools_py in sorted((ROOT / "mcp-servers").glob("*/tools.py")):
        spec = importlib.util.spec_from_file_location(f"_tools_{tools_py.parent.name}", tools_py)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for tool in module.TOOLS:
            props = (tool.get("inputSchema") or {}).get("properties") or {}
            found[f"mcp__{tools_py.parent.name}__{tool['name']}"] = set(props)
    return found


def _agent_tools(agent: Path) -> set[str]:
    head = agent.read_text(encoding="utf-8").split("---")[1]
    line = next(l for l in head.splitlines() if l.startswith("tools:"))
    return {t.strip() for t in line.removeprefix("tools:").split(",") if t.strip()}


def _files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.md"))


AGENTS = {p.stem: p for p in sorted((CLAUDE / "agents").glob("*.md"))}


def _readers(path: Path) -> list[str]:
    """The agents that read `path`: its own agent, or agents/commands that point at it."""
    if path.parent.name == "agents":
        return [path.stem]
    if path.parent.name == "commands":
        text = path.read_text(encoding="utf-8")
        return [name for name in AGENTS if f"agents/{name}.md" in text]
    skill = path.relative_to(CLAUDE / "skills").parts[0]
    return [
        name for name, agent in AGENTS.items()
        if f"skills/{skill}/" in agent.read_text(encoding="utf-8")
    ]


FILES = _files(CLAUDE / "agents") + _files(CLAUDE / "commands") + _files(CLAUDE / "skills")


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CLAUDE)).replace("\\", "/"))
def test_every_named_tool_exists_and_its_readers_have_it(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    named = {f"mcp__{s}__{t}" for s, t in TOOL_REF.findall(text)}
    unknown = sorted(named - set(_schemas()))
    assert not unknown, f"{path.name} names tools no server defines: {unknown}"
    missing = {
        agent: sorted(named - _agent_tools(AGENTS[agent]))
        for agent in _readers(path)
    }
    missing = {agent: tools for agent, tools in missing.items() if tools}
    assert not missing, f"{path.name} tells these agents to use tools they lack: {missing}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CLAUDE)).replace("\\", "/"))
def test_example_arguments_exist_on_the_tool(path: Path) -> None:
    schemas = _schemas()
    wrong = []
    for server, tool, args in CALL.findall(path.read_text(encoding="utf-8")):
        name = f"mcp__{server}__{tool}"
        for arg in ARG.findall(args):
            if name in schemas and arg not in schemas[name]:
                wrong.append(f"{name}({arg}=)")
    assert not wrong, f"{path.name} passes arguments the tool does not take: {wrong}"
