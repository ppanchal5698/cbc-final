"""The toolset registry and .mcp.json must not drift apart.

`cbc_core/toolsets.py` hardcodes `SERVERS` (name -> script) to build the
`--mcp-config` for each job; `.mcp.json` is the inventory Claude Code reads. A
server named in one but not the other fails in a way that is easy to miss: named
in `SERVERS` but absent from `.mcp.json` and a scoped run cannot launch it;
present in `.mcp.json` but absent from `SERVERS` and it is silently never scoped
in. These pin the two together so the next server is added to both.
"""
from __future__ import annotations

import json

from cbc.modules.ops.api import toolsets
from tests.shared import ROOT


def _mcp_json_servers() -> dict[str, dict]:
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    return data["mcpServers"]


def test_servers_match_the_mcp_json_registry() -> None:
    assert set(toolsets.SERVERS) == set(_mcp_json_servers())


def test_server_scripts_match_the_mcp_json_args() -> None:
    registry = _mcp_json_servers()

    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    for name, script in toolsets.SERVERS.items():
        assert _norm(registry[name]["args"][0]) == _norm(script), name


def test_scoped_mcp_args_are_absolute() -> None:
    """Scratch-dir cwd cannot resolve ./mcp-servers; flags must be absolute."""
    from pathlib import Path

    servers = json.loads(toolsets.config_for("extract_bid_set"))["mcpServers"]
    for name, entry in servers.items():
        assert Path(entry["args"][0]).is_absolute(), name


def test_pricing_can_read_the_page_it_is_sent_to():
    """The catalog tools return a page; reading it needs pdf-tools.

    Pricing used to read an extracted product table and genuinely needed no PDF,
    so the profile withheld pdf-tools. After the catalog became a page index that
    left a pass able to find the page and unable to open it - a real run called
    find_pages, got its page, called extract_tables, was told no such tool exists,
    and wrote all 32 lines MANUAL.
    """
    import json

    from cbc.modules.ops.api import toolsets

    servers = json.loads(toolsets.config_for("match_and_price"))["mcpServers"]
    assert "catalog" in servers, "pricing needs the page index"
    assert "pdf-tools" in servers, "and the means to read the page it names"


def test_a_take_off_still_cannot_see_the_pricing_tools():
    """Adding pdf-tools to pricing must not widen extraction the other way."""
    import json

    from cbc.modules.ops.api import toolsets

    servers = json.loads(toolsets.config_for("extract_bid_set"))["mcpServers"]
    assert set(servers) == {"pdf-tools", "artifact-storage", "reference"}
    for absent in ("catalog", "calc-engine", "p21-connector"):
        assert absent not in servers


def test_ingest_can_read_the_sheet_it_is_given():
    """Same trap as pricing, and here it was total.

    `ingest_pricebook` exists to read a vendor PDF and write the parts off it.
    Its profile listed catalog and artifact-storage - the index that says which
    page to open, and somewhere to put the answer, with nothing in between that
    opens a page.
    """
    import json

    from cbc.modules.ops.api import toolsets

    servers = json.loads(toolsets.config_for("ingest_pricebook"))["mcpServers"]
    assert "pdf-tools" in servers, "ingest must be able to open the sheet"


def test_pricing_hands_p21_the_readonly_mongo_uri(monkeypatch):
    """check_freshness reads the admin window from settings; that needs the RO URI."""
    monkeypatch.setenv("MONGODB_READONLY_URI", "mongodb://ro@localhost/cbc_opshub")
    servers = json.loads(toolsets.config_for("match_and_price"))["mcpServers"]
    assert servers["p21-connector"]["env"]["MONGODB_READONLY_URI"].startswith("mongodb://")
    assert servers["catalog"]["env"]["MONGODB_READONLY_URI"].startswith("mongodb://")


def test_every_job_type_is_either_a_prompt_or_a_local_handler(wired_worker):
    """A job type nobody runs is a queue entry that fails at dispatch.

    `index_document` and `delete_document` sat in this Literal after the deep-index
    subsystem was deleted: enqueueable from the API, labelled in the job list, and
    with no template and no handler, so they raised out of `prompts.build()`. The
    two sets must partition the Literal exactly - a type in neither is unrunnable,
    and a type in both has two implementations.
    """
    import typing

    from cbc.worker_kit import prompts
    from cbc.modules.ops.domain.jobs import JobType

    declared = set(typing.get_args(JobType))
    served = set(wired_worker._handlers)
    local = {t for t, h in wired_worker._handlers.items() if getattr(h, "func", None) is wired_worker.run_locally}

    assert not declared - served, f"job types nothing runs: {sorted(declared - served)}"
    assert not served - declared, f"handlers for undeclared types: {sorted(served - declared)}"
    assert set(prompts.TEMPLATES) == served - local, "a Claude pass with no template, or a local job with one"

