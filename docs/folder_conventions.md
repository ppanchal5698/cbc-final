# Folder conventions

## Live (compose / local monolith)

| Path | Owns |
|---|---|
| `apps/backend/src/cbc/app/` | API composition root (`create_app`): middleware, error mapping, lifespan, module registration |
| `apps/backend/src/cbc/worker/` | Worker composition root: `python -m cbc.worker` registers every module's jobs into ops' loop |
| `apps/backend/src/cbc/modules/<module>/api/` | The module's public surface - the only part another module may import |
| `apps/backend/src/cbc/modules/<module>/features/` | One file per use case (endpoint or job) |
| `apps/backend/src/cbc/modules/<module>/domain/` | Request models and pure rules the module's slices share |
| `apps/backend/src/cbc/modules/<module>/infrastructure/` | The module's collections, indexes and adapters |
| `apps/backend/src/cbc/shared/` | Config, auth, Mongo client + primitives, events, logging, tracing |
| `apps/backend/src/cbc/{core,domain,pageindex,persistence,validation}/` | Kernel packages the modules build on |
| `apps/backend/src/cbc/{db.py,schemas,worker_kit}/` | Legacy kernel, being worked down (see ARCHITECTURE.md) |
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

See [`archive/pre-monolith/README.md`](../archive/pre-monolith/README.md) for restore steps.

## Rules

1. New backend work goes in a module slice under `apps/backend/src/cbc/modules/`.
2. A module reaches another only through `cbc.modules.<other>.api`; see
   [ARCHITECTURE.md](../ARCHITECTURE.md) and `apps/backend/tests/architecture/test_layering.py`.
3. A module reads and writes only its own collections.
4. Money math lives only in pure domain calc (not in routes).
5. Do not start archived `services/*-api`; the live API is `platform`.
6. Shell workflows (`workflows/_phase.sh`, etc.) use `PYTHONPATH=…/apps/backend/src`.
