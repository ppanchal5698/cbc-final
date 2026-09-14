"""An agent's frontmatter and its body have to agree about what it can do.

`quality-reviewer` was told - by the build_proposal prompt and by its own Output
section - to run `scripts/render_review_summary.py`. Its tools were
`Read, Glob, Grep, Write`. Every proposal run therefore reached a step it had no
tool to take, and the only way to notice was to read two files side by side.

These read them side by side.
"""
from __future__ import annotations

import re

import pytest

from cbc.modules.ops.api import toolsets
from tests.shared import ROOT

AGENT_DIR = ROOT / ".claude" / "agents"
AGENTS = sorted(AGENT_DIR.glob("*.md"))
assert AGENTS, "no agent definitions found"


def _frontmatter_tools(text: str) -> list[str]:
    match = re.search(r"^tools:\s*(.+)$", text, re.MULTILINE)
    return [t.strip() for t in match.group(1).split(",")] if match else []


def _body(text: str) -> str:
    parts = text.split("---", 2)
    return parts[2] if len(parts) > 2 else text


_MCP_TOOL = re.compile(r"mcp__[\w-]+__[\w-]+")


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_every_mcp_tool_named_in_the_body_is_allowed(path) -> None:
    text = path.read_text(encoding="utf-8")
    allowed = set(_frontmatter_tools(text))
    for match in _MCP_TOOL.finditer(_body(text)):
        tool = match.group(0)
        assert tool in allowed, (
            f"{path.stem} body names {tool!r} but tools: frontmatter omits it"
        )


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_an_agent_told_to_run_a_script_can_run_one(path) -> None:
    text = path.read_text(encoding="utf-8")
    runs_a_script = re.search(r"`?python[ \w./-]*\.py", _body(text))
    if not runs_a_script:
        pytest.skip("no script invocation in this agent")
    assert "Bash" in _frontmatter_tools(text), (
        f"{path.stem} is told to run {runs_a_script.group(0)!r} without Bash"
    )


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_every_mcp_tool_belongs_to_a_server_that_exists(path) -> None:
    text = path.read_text(encoding="utf-8")
    for tool in _frontmatter_tools(text):
        if not tool.startswith("mcp__"):
            continue
        server = tool.split("__")[1]
        assert server in toolsets.SERVERS, f"{path.stem} lists tool from {server!r}"


def test_intake_coordinator_has_pdf_tools_for_metadata() -> None:
    """Intake reads title blocks from bid sets; without pdf-tools it falls back to
    Read (needs poppler) or ad-hoc Bash/fitz scripts."""
    text = (AGENT_DIR / "intake-coordinator.md").read_text(encoding="utf-8")
    tools = _frontmatter_tools(text)
    assert any(t.startswith("mcp__pdf-tools__") for t in tools), (
        "intake-coordinator must list pdf-tools so it can extract metadata"
    )


def test_the_delegation_rule_names_agents_that_exist() -> None:
    """The orchestrator picks `subagent_type` from this list.

    A name here that has no file is a delegation that fails at the call, several
    minutes into a run, with the phase's output never written.
    """
    from cbc.worker_kit import prompts

    listed = re.search(
        r"subagent_type: one of (.+?)\n\s*prompt:",
        prompts.DELEGATION_RULE,
        re.DOTALL,
    )
    assert listed, "the delegation rule no longer lists subagent types"
    names = {n.strip().rstrip(",") for n in listed.group(1).replace("\n", " ").split(",")}
    names = {n for n in names if n}

    on_disk = {p.stem for p in AGENTS}
    assert not names - on_disk, f"delegated to agents that do not exist: {names - on_disk}"
    assert "quote-builder" not in names


def test_mechanical_agents_declare_haiku_and_judgment_stays_sonnet() -> None:
    def model_of(stem: str) -> str:
        text = (AGENT_DIR / f"{stem}.md").read_text(encoding="utf-8")
        match = re.search(r"^model:\s*(\S+)", text, re.MULTILINE)
        assert match, stem
        return match.group(1)

    for name in ("intake-coordinator", "delivery-agent", "pricebook-ingestor"):
        assert model_of(name) == "haiku", name
    for name in ("takeoff-engineer", "product-matcher", "pricing-engineer"):
        assert model_of(name) == "sonnet", name


def test_no_agent_claims_a_server_the_deleted_alias_used_to_serve() -> None:
    """`pricebook` was an alias over `catalog`; both the agent body and the ingest
    prompt still sent runs to it long after it stopped existing."""
    for path in AGENTS:
        body = path.read_text(encoding="utf-8")
        assert "`pricebook` MCP" not in body, path.stem


def test_takeoff_engineer_is_review_first_and_save_artifact_only() -> None:
    """Closed-world takeoff: no freehand invent, no Write bypass of schema."""
    text = (AGENT_DIR / "takeoff-engineer.md").read_text(encoding="utf-8")
    tools = _frontmatter_tools(text)
    body = _body(text)
    assert "Write" not in tools
    assert "mcp__artifact-storage__save_artifact" in tools
    assert "Fixed procedure" in body or "review-first" in body.lower() or "Read first" in body
    assert "parse_schedule.py" in body
    assert "page_size" in body
    assert "thickness" in body.lower()
    assert "save_artifact" in body
    assert "Never use Write" in body or "never Write" in body.lower()
    assert "PDF verify" in body or "pdf-verify-before-present" in body
    assert "evidence_note" in body
    assert "get_page_blocks" in body or "search_blocks" in body


def test_quality_reviewer_can_open_the_pdf_when_unclear() -> None:
    """Reviewer must verify unclear flags on the sheet, not only restate JSON."""
    text = (AGENT_DIR / "quality-reviewer.md").read_text(encoding="utf-8")
    tools = _frontmatter_tools(text)
    body = _body(text)
    assert any(t.startswith("mcp__pdf-tools__") for t in tools)
    assert "PDF verify" in body or "pdf-verify-before-present" in body
    assert "get_page_blocks" in body or "search_blocks" in body


def test_extraction_agents_omit_write_for_checkpoints() -> None:
    for stem in ("intake-coordinator", "spec-scope-analyst", "frp-specialist", "takeoff-engineer"):
        tools = _frontmatter_tools((AGENT_DIR / f"{stem}.md").read_text(encoding="utf-8"))
        assert "Write" not in tools, f"{stem} must not list Write (use save_artifact)"
        assert "mcp__artifact-storage__save_artifact" in tools, stem

