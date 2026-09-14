# Architecture

CBC Estimating Copilot runs as a **modular monolith**. The full description - modules,
what each owns, the dependency rule, the seams between modules, and how to add a slice
or a module - is in [ARCHITECTURE.md](../ARCHITECTURE.md) at the repository root.
The decision record is [ADR-005](adr/005-modules-own-their-data.md), which supersedes
[ADR-004](adr/004-modular-monolith-apps-backend.md)'s dependency rule.

```
apps/web  ──►  platform API (apps/backend :8001, cbc.app.main:create_app)  ──►  MongoDB
                      modules/{ops,projects,catalog,intake,extraction,pricing,quoting}
worker (WORKER_CLAIM_ALL=1, python -m cbc.app.worker)  ──►  Claude CLI + MCP
parser (profile gpu, WORKER_DOMAIN=parsing)  ──►  mineru (:8000, compose-only)  ──►  documentPages
```

Compose service name for the API remains `platform`; one `worker` claims Claude / pipeline
jobs. With `COMPOSE_PROFILES=gpu`, a separate `parser` worker runs `parse_document` against
the `mineru` GPU service and stores blocks in `documentPages`. There is no HTTP between
modules; API and workers share MongoDB, disk/S3 and the job queue.

## Dependency rule

A module imports another only through `cbc.modules.<other>.api`; nothing outside a module
imports its `features`, `domain` or `infrastructure`; `shared` imports no module; no module
names another module's collection. Enforced by
`apps/backend/tests/architecture/test_layering.py`.

## Data model

See [collections.mongodb.md](collections.mongodb.md) for the collection specification and
[data_model.md](data_model.md) for what is implemented.

## Runtime

See [app_lifecycle.md](app_lifecycle.md). Start the stack with:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Health: `GET http://127.0.0.1:8001/api/health` (`service: platform`).

## Tuning the parser

Two kinds of settings (do not mix them):

| Kind | Where | When it applies |
| --- | --- | --- |
| **Runtime** (`PARSER_*`) | process env, mounted `.env`, Settings → parsing, or profile preset | next `parse_document` job; no restart |
| **Container** (`MINERU_*`, `PARSER_WORKER_CONCURRENCY`, `MINERU_SHM_SIZE`) | `infra/mineru/{low,medium,high}.env` via compose `--env-file` | rebuild/restart of `mineru` / `parser` |

Never set `MINERU_FORMULA_ENABLE` / `MINERU_TABLE_ENABLE` on the container — they override
request bodies; use `PARSER_TABLES` / `PARSER_FORMULAS` instead. Empty `PARSER_URL` means
parsing is off (extraction falls back to pdf-tools).

### High-spec checklist

1. `docker compose -f infra/docker-compose.yml --env-file .env --env-file infra/mineru/high.env --profile gpu up -d --build`
2. Settings → High → Test with a sample page
3. Upload Dutch Bros and compare `runMetrics` to the pre-MinerU baseline
