"""What a run is allowed to cost before it has read a single drawing.

The first real bid set spent a million-token budget without producing a
schedule. Most of that was avoidable in ways that are easy to reintroduce: a doc
inlined into every session, a tool that returns a whole set in one call, a phase
that can see tools belonging to another phase.

These pin the things that were expensive, so the next person to add an `@` to
CLAUDE.md finds out here rather than three runs later.
"""
from __future__ import annotations

import json
import re

import pytest

from tests.shared import ROOT  # noqa: E402

from _runtime import dump_payload, load_server  # noqa: E402
from cbc.core import toolsets  # noqa: E402

pdf = load_server("pdf-tools")
MIS_ENCODED = ROOT / "tests" / "fixtures" / "pdfs" / "Bid Set .pdf"
needs_set = pytest.mark.skipif(not MIS_ENCODED.exists(), reason="fixture not present")


# â”€â”€ what every session carries before it starts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def inlined_size() -> int:
    """CLAUDE.md plus everything it pulls in with `@`."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    total = len(text)
    for reference in re.findall(r"@([\w/.\-]+\.md)", text):
        target = ROOT / reference
        if target.exists():
            total += len(target.read_text(encoding="utf-8"))
    return total


def test_the_always_loaded_context_stays_small():
    """This was 72 KB - about 18,000 tokens spent before reading a sheet.

    `@` inlines a file into every session and every turn, so a doc added here is
    paid for on every job forever. Reference it by path instead unless a run is
    genuinely following it.
    """
    assert inlined_size() < 20_000, (
        f"CLAUDE.md now inlines {inlined_size():,} chars. Use a plain path, not @."
    )


def test_no_document_is_inlined_twice():
    """`opshub_setup.md` was inlined twice - 26 KB of Docker troubleshooting."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    references = re.findall(r"@([\w/.\-]+\.md)", text)
    duplicates = {r for r in references if references.count(r) > 1}
    assert not duplicates, f"inlined more than once: {duplicates}"


def test_agents_do_not_inline_project_rules():
    """Rules under .claude/rules/ load automatically â€” @-inlining duplicates context."""
    agents = ROOT / ".claude" / "agents"
    offenders = []
    for path in agents.glob("*.md"):
        if "@.claude/rules/" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"agents still @-inline rules: {offenders}"


# â”€â”€ each phase sees only its own tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_take_off_cannot_see_the_pricing_tools():
    """Nothing is priced during extraction, so nothing pricing-shaped should be
    on offer. Fewer wrong tools is a quality lever, not only a cost one."""
    servers = json.loads(toolsets.config_for("extract_bid_set"))["mcpServers"]

    # `reference` is finishes, frame depths and FRP constants - take-off data,
    # not prices.
    assert set(servers) == {"pdf-tools", "artifact-storage", "reference"}
    for absent in ("catalog", "calc-engine", "p21-connector"):
        assert absent not in servers


def test_pricing_gets_the_tools_it_needs():
    servers = json.loads(toolsets.config_for("match_and_price"))["mcpServers"]

    for needed in ("catalog", "calc-engine", "p21-connector"):
        assert needed in servers
    # pdf-tools used to be excluded here because the schedule was already
    # extracted and pricing read a product table. The catalog now returns a page
    # to open, so a pass without pdf-tools can find the price and not read it.
    assert "pdf-tools" in servers


def test_preflight_loads_no_mcp_servers():
    """Empty PROFILES['preflight'] must stay empty â€” `[] or list(SERVERS)` would
    silently reload every server and blow small-context models on Test."""
    servers = json.loads(toolsets.config_for("preflight"))["mcpServers"]
    assert servers == {}


def test_an_unknown_job_type_still_gets_every_server():
    """A new job type must not silently run with no tools at all."""
    servers = json.loads(toolsets.config_for("something_new"))["mcpServers"]
    assert set(servers) == set(toolsets.SERVERS)


def test_the_run_is_scoped_and_strict():
    flags = toolsets.flags_for("extract_bid_set")

    assert "--strict-mcp-config" in flags, "otherwise .mcp.json adds the rest back"
    assert "--disallowed-tools" in flags
    assert "WebSearch" in flags and "WebFetch" in flags


def test_every_profile_names_real_servers():
    for job_type, names in toolsets.PROFILES.items():
        unknown = set(names) - set(toolsets.SERVERS)
        assert not unknown, f"{job_type} names servers that do not exist: {unknown}"


# â”€â”€ no single call may swallow the context â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_mcp_payloads_drop_json_indent():
    """Whitespace was ~60% of every tool result (T-01). Semantics must not change."""
    payload = {
        "pages": [
            {"source_page": n, "rows": [{"cells": ["A", "B"], "text": "A | B"}] * 20}
            for n in range(1, 6)
        ]
    }
    compact = dump_payload(payload)
    pretty = json.dumps(payload, indent=2, default=str)
    assert json.loads(compact) == json.loads(pretty)
    saved = 1 - len(compact) / len(pretty)
    assert saved >= 0.35, f"compact form only saved {saved:.1%}"


@needs_set
def test_finding_the_right_sheets_is_cheap():
    """Six searches cost six turns and ~2,300 tokens to answer one question."""
    result = pdf.find_sheets(str(MIS_ENCODED))
    size = len(json.dumps(result))

    assert size < 6_000, f"page map cost {size:,} chars"
    assert result["pages"], "found no candidate sheets at all"
    assert result["pages"][0]["score"] >= result["pages"][-1]["score"], "not ranked"


@needs_set
def test_the_page_map_reports_terms_it_could_not_find():
    """A term that is absent is an answer, not a gap to be guessed around."""
    result = pdf.find_sheets(str(MIS_ENCODED), queries=["door", "zzzz-not-present"])
    assert "zzzz-not-present" in result["not_found"]


@needs_set
def test_reading_a_whole_set_in_one_call_is_bounded():
    """This returned 1.5 million characters - roughly 385,000 tokens."""
    result = pdf.extract_tables(str(MIS_ENCODED), page_range="all")
    compact = dump_payload(result)
    pretty = json.dumps(result, indent=2, default=str)
    size = len(compact)

    assert size < 400_000, f"one call returned {size:,} chars"
    assert json.loads(compact) == json.loads(pretty)
    assert result["pages_deferred"], "a 28-page set should have deferred pages"
    assert result["note"], "deferred pages must be named, not silently dropped"


@needs_set
def test_mcp_tool_results_are_compact():
    """Pretty-print was ~60% of an extract_tables payload (T-01)."""
    result = pdf.extract_tables(str(MIS_ENCODED), page_range="all")
    compact = dump_payload(result)
    pretty = json.dumps(result, indent=2, default=str)
    assert json.loads(compact) == json.loads(pretty)
    saved = 1 - len(compact) / len(pretty)
    assert saved >= 0.35, f"compact form only saved {saved:.1%}"


@needs_set
def test_search_returns_locations_not_documents():
    result = pdf.search_pdf(str(MIS_ENCODED), "DOOR")
    size = len(json.dumps(result))

    assert size < 15_000, f"search returned {size:,} chars"


# â”€â”€ the prompt does not invite the expensive patterns â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_the_prompt_names_subagents_rather_than_files():
    """Naming a path invites `cat`, which puts the whole file in the context.

    The first run read five of its own instruction files that way, ~22 KB.
    """
    from cbc.worker_kit import prompts

    extract = prompts.EXTRACT
    assert ".claude/agents/" not in extract, "a path here gets cat'd"
    assert "takeoff-engineer" in extract
    assert "find_sheets" in extract


def test_the_preamble_forbids_reimplementing_the_tools():
    from cbc.worker_kit import prompts

    assert "reimplement" in prompts.PREAMBLE.lower()
    assert "cat" in prompts.PREAMBLE.lower()

