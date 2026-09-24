"""Which tools each job type gets.

Every MCP server's schema sits in the context for the whole run, and every tool
in it is a candidate the model has to consider. A take-off pass that can see
`lookup_last_po` and `validate_margin` is paying for them twice: once in tokens,
and again in the chance it reaches for the wrong one.

So each job gets the servers its phase actually uses. `--strict-mcp-config` makes
the list exhaustive rather than additive, so nothing leaks in from `.mcp.json`.

This is a quality lever as much as a cost one. The cost is small and measurable
(~11 KB of schema down to ~4 KB on an extraction); the quality effect is that
the only tools on offer are the right ones.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from cbc.shared.paths import repo_root

REPO_ROOT = repo_root()

# Server name -> the script that serves it, mirroring .mcp.json.
SERVERS = {
    "pdf-tools": "mcp-servers/pdf-tools/server.py",
    "calc-engine": "mcp-servers/calc-engine/server.py",
    "artifact-storage": "mcp-servers/artifact-storage/server.py",
    "p21-connector": "mcp-servers/p21-connector/server.py",
    "catalog": "mcp-servers/catalog/server.py",
    "reference": "mcp-servers/reference/server.py",
    "bid-docs": "mcp-servers/bid-docs/server.py",
    "catalog-docs": "mcp-servers/catalog-docs/server.py",
}

# Reading drawings and writing what was found. Reference for finishes / frame
# depths / FRP constants during take-off; bid-docs for parsed blocks; no pricing.
_READING = ["pdf-tools", "artifact-storage", "reference", "bid-docs"]

# Costing a confirmed schedule: the catalog for what things cost, calc-engine for
# the arithmetic, p21 for last-PO history.
#
# `catalog` used to appear here beside a `pricebook` server that was a pure alias
# over it, so a pricing pass carried search_product, list_vendors, lookup_pricing
# and get_multiplier twice under two names - the exact duplication this module
# exists to prevent.
#
# `pdf-tools` belongs here now, and did not before. Pricing used to read an
# extracted product table, so it genuinely needed no PDF - the profile said as
# much. The catalog tools return a *page* to open, and the price is read off that
# page, so withholding pdf-tools leaves a pass able to find the page and unable
# to read it. That is exactly what happened: a run called find_pages, got its
# page, called extract_tables, was told no such tool exists, and wrote all 32
# lines MANUAL.
_PRICING = [
    "catalog",
    "catalog-docs",
    "reference",
    "pdf-tools",
    "calc-engine",
    "p21-connector",
    "artifact-storage",
]

# One run that spans every phase needs every server. Per-phase scoping is a real
# cost and quality lever when a job does one thing; here the same pass reads
# drawings, prices lines and writes artifacts, so narrowing it would only make a
# subagent reach for a tool it has not been given.
_EVERYTHING = list(SERVERS)

PROFILES: dict[str, list[str]] = {
    "run_full_pipeline": _EVERYTHING,
    "extract_bid_set": _READING,
    "rerun_extraction": _READING,
    "ingest_addendum": _READING,
    "match_and_price": _PRICING,
    # The proposal totals an already-priced quote, but the `quality-reviewer` that
    # runs in this phase verifies unclear findings against the specific PDF page -
    # so it needs `bid-docs` (parsed blocks) and `pdf-tools` (open the sheet). This
    # is the _PRICING / ingest_pricebook trap again: an agent told to check the
    # drawing, given no tool that reads one. `build_proposal` declared three
    # bid-docs and four pdf-tools tools in its own frontmatter that never started.
    "build_proposal": [
        "calc-engine",
        "reference",
        "artifact-storage",
        "bid-docs",
        "pdf-tools",
    ],
    # Ingest reads a vendor sheet and writes what it found. `pdf-tools` is the
    # only way to read it - the same trap as _PRICING above, and here it was
    # total: the profile gave a job whose entire purpose is "read this PDF" no
    # tool that opens a PDF.
    "ingest_pricebook": ["catalog", "reference", "pdf-tools", "artifact-storage"],
}

# Built-in tools no bid job has a use for. Bare names remove them from the
# context entirely rather than merely denying the call.
#
# A pass over a customer's drawings has no reason to reach the network, and
# saying so here is cheaper and clearer than trusting it not to.
DISALLOWED = ["WebSearch", "WebFetch", "NotebookEdit"]

# Settings → Test connection and worker --preflight only need a short round-trip.
# Loading every MCP schema is wasted cost for a one-line connectivity check.
PREFLIGHT = "preflight"
PROFILES[PREFLIGHT] = []



def _readonly_uri() -> str | None:
    """The read-only connection string for catalog MCP servers.

    Prefer the env var. Callers that already resolved `cbc.shared.mongo.readonly_uri` may
    set `READONLY_URI_OVERRIDE` before building the config.
    """
    return os.environ.get("READONLY_URI_OVERRIDE") or os.environ.get("MONGODB_READONLY_URI")


def config_for(job_type: str) -> str:
    """The `--mcp-config` payload for a job type, as a JSON string.

    The catalog server reads the page index from MongoDB with a credential that
    cannot write.
    """
    names = PROFILES[job_type] if job_type in PROFILES else list(SERVERS)
    servers: dict[str, Any] = {}
    for name in names:
        if name not in SERVERS:
            continue
        # sys.executable, not bare "python". On an image whose interpreter is
        # python3, or with a venv that is not first on the subprocess PATH, every
        # server failed to start - and a run with no tools does not error, it
        # writes every line MANUAL and reports success. quoting's render.py has
        # always done it this way.
        entry: dict[str, Any] = {
            "command": sys.executable,
            "args": [str((REPO_ROOT / SERVERS[name]).resolve())],
        }
        env: dict[str, str] = {}
        if name in ("catalog", "p21-connector", "reference", "bid-docs", "catalog-docs"):
            # Page index, freshness, referenceData, and parsed bid/catalog blocks use a
            # read-only credential with no fallback to the writable string.
            readonly = _readonly_uri()
            if readonly:
                env["MONGODB_READONLY_URI"] = readonly
            if os.environ.get("MONGODB_DB"):
                env["MONGODB_DB"] = os.environ["MONGODB_DB"]
            if name == "reference" and os.environ.get("REFERENCE_DIR"):
                env["REFERENCE_DIR"] = os.environ["REFERENCE_DIR"]
        if env:
            entry["env"] = env
        servers[name] = entry
    return json.dumps({"mcpServers": servers})


def flags_for(job_type: str) -> list[str]:
    """CLI flags scoping a run to the tools its phase needs."""
    return [
        "--mcp-config",
        config_for(job_type),
        "--strict-mcp-config",
        "--disallowed-tools",
        *DISALLOWED,
    ]


if __name__ == "__main__":  # `python -m cbc.modules.ops.api.toolsets <job_type>`
    # One flag per line, for the shell entry points in workflows/. They used to
    # spawn the CLI with no scoping at all, so a headless take-off carried every
    # server in .mcp.json plus WebSearch and WebFetch - the exact surface this
    # module exists to withhold, withheld only from the worker. The JSON payload
    # contains no newlines, so a line is a flag.
    if len(sys.argv) != 2:
        sys.exit("usage: python -m cbc.modules.ops.api.toolsets <job_type>")
    if sys.argv[1] not in PROFILES:
        sys.exit(
            f"unknown job type {sys.argv[1]!r}; expected one of "
            + ", ".join(sorted(PROFILES))
        )
    for flag in flags_for(sys.argv[1]):
        print(flag)
