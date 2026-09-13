"""reference MCP exposes only read tools."""
from __future__ import annotations

from _runtime import load_server
from tests.shared import ROOT  # noqa: F401  - puts mcp-servers on sys.path

# A bare `from tools import TOOLS` here read whichever server's tools module was
# already in sys.modules - p21-connector's, when the suite ran in one process -
# and asserted about the wrong server. `load_server` exists for exactly this.
TOOLS = load_server("reference").TOOLS


def test_reference_mcp_has_no_write_tools() -> None:
    forbidden = ("write", "update", "insert", "upsert", "delete", "create", "set_", "put_")
    bad = [t["name"] for t in TOOLS if any(w in t["name"].lower() for w in forbidden)]
    assert bad == []
    assert "get_margin_bands" in {t["name"] for t in TOOLS}
