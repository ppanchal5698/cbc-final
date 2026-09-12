# Folder conventions

## Live (compose / local monolith)

| Path | Owns |
|---|---|
| `apps/backend/src/cbc/domain/` | Pure estimating rules |
| `apps/backend/src/cbc/schemas/` | Pydantic shapes |
| `apps/backend/src/cbc/services/` | Application services (pricing, quote, sync, …) |
| `apps/backend/src/cbc/modules/{platform,…}/` | Domain HTTP + jobs stubs |
| `apps/backend/src/cbc/worker_kit/` | Claude worker runtime |
| `apps/backend/src/cbc/worker/` | `python -m cbc.worker` entry |
| `apps/backend/src/cbc/pageindex/` | Vendor catalog page index |
| `apps/backend/src/cbc/http/` | Shared FastAPI helpers |
| `apps/web/` | Next.js Ops-Hub |
| `mcp-servers/` | One folder per MCP server; shared `_runtime` |
| `.claude/` | Single agent-runtime source; Docker copies to `/app/agent-runtime` |
| `docs/` | Architecture, data model, traceability, ADRs |
| `infra/` | Compose + container entrypoint |
| `data/` | Runtime volumes (projects, pricebooks, reference-library) |
| Root `pyproject.toml` | Editable install of `apps/backend/src` (`pip install -e .`) |

## Archived (rollback only)

| Path | Owns |
|---|---|
| `archive/pre-monolith/packages/cbc/` | Pre-cutover shared kernel mirror |
| `archive/pre-monolith/services/{domain}/` | Pre-cutover thin routers + workers |
| `archive/pre-monolith/Dockerfile` | Pre-cutover multi-service image |
| `archive/pre-monolith/tests/` | Legacy api/pipeline/catalog suites (not CI-gated) |

See [`archive/pre-monolith/README.md`](../../archive/pre-monolith/README.md) for restore steps.

## Rules

1. Prefer new work under `apps/backend/src/cbc/` and `apps/web/`.
2. No upward imports across module API layers (see
   `apps/backend/tests/architecture/test_layering.py`).
3. Money math lives only in pure domain calc (not in routers).
4. Do not start archived `services/*-api`; the live API is `platform`.
5. Shell workflows (`workflows/_phase.sh`, etc.) use
   `PYTHONPATH=…/apps/backend/src`.
