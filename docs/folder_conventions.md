# Folder conventions

| Path | Owns |
|---|---|
| `packages/cbc/domain/` | Pure estimating rules |
| `packages/cbc/contracts/` | Pydantic shapes (preferred); `schemas/` is the shim |
| `packages/cbc/persistence/` | Mongo repositories, migrations, names |
| `packages/cbc/{extraction,pricing,quoting,platform}/` | Domain packages (re-export services during rename) |
| `packages/cbc/agents/` | Claude worker runtime (preferred); `worker_kit/` is the shim |
| `packages/cbc/http/` | Shared FastAPI factory |
| `services/{domain}/api/` | Thin routers only |
| `services/{domain}/worker/` | Entry that calls `cbc.agents` / `worker_kit` |
| `mcp-servers/` | One folder per MCP server; shared `_runtime` |
| `.claude/` | Single agent-runtime source; Docker copies to `/app/agent-runtime` |
| `apps/web/` | Next.js Ops-Hub |
| `docs/` | Architecture, data model, traceability, ADRs |
| `tests/` | `api/`, `pipeline/`, `catalog/` |

## Rules

1. No `sys.path.insert` under `packages/`, `services/`, `scripts/`, `mcp-servers/`.
2. No upward imports inside `packages/cbc` (see `tests/api/test_layering.py`).
3. Collection names are spelled once in `cbc.persistence.names`.
4. Money math lives only in `cbc.domain.calc`.
