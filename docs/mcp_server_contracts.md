# MCP server contracts

Six servers, one shared stdio runtime (`mcp-servers/_runtime.py`), installed via
`pip install -e ./mcp-servers` so `import _runtime` needs no path hacks.

| Server | Role | Writes? |
|---|---|---|
| pdf-tools | PDF text, tables, page images | No (reads files) |
| catalog | Page index — which page to open | Read-only Mongo |
| calc-engine | Quote arithmetic adapter over `cbc.domain.calc` | No |
| artifact-storage | Versioned project artifact writes | Yes (project tree only) |
| p21-connector | Last-PO lookup | Read-only |
| reference | Reference library families | Read-only Mongo |

Toolsets per job type: `packages/cbc/core/toolsets.py`.
