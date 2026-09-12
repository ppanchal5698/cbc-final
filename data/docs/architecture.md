# Architecture

CBC Estimating Copilot runs as a **modular monolith**.

```
apps/web  ──►  platform (apps/backend :8001)  ──►  MongoDB
                      │
                      ├── modules/{platform,intake,extraction,pricing,quoting,catalog}
                      ├── shared kernel (domain, schemas, services, pageindex, …)
                      └── enqueue jobs
worker (WORKER_CLAIM_ALL=1)  ──►  claim any job  ──►  Claude CLI + MCP
```

Compose service name for the API remains `platform`; one `worker` claims all
job types. There is **no** inter-service HTTP between domains; the worker and
API share MongoDB, disk/S3, and the job queue.

Legacy trees `services/` and `packages/cbc` (plus the pre-cutover root
`Dockerfile` and root `tests/`) are archived under `archive/pre-monolith/` for
rollback. They are not the default compose runtime path. See
[ADR-004](adr/004-modular-monolith-apps-backend.md).

## Live package layout

```
apps/backend/src/cbc/
  api/              FastAPI factory (mounts all module routers)
  modules/          vertical slices: api / application / domain / jobs
  domain/           pure estimating rules
  schemas/          Pydantic contracts
  services/         application services (pricing, quote, sync, …)
  worker_kit/       Claude job claim loop + handlers
  worker/           `python -m cbc.worker` entry
  pageindex/        vendor catalog page index
  http/             shared FastAPI helpers
mcp-servers/        six MCP servers on shared _runtime
apps/web/           Next.js Ops-Hub (PLATFORM_URL, audience platform)
```

## Dependency rule

Module routers must not import another module’s API layer. Enforced by
`apps/backend/tests/architecture/test_layering.py`.

```
modules.*.api  →  shared kernel (services, domain, schemas, db)
worker_kit     →  shared kernel + pageindex + validation
```

## Data model

See [collections.mongodb.md](collections.mongodb.md) for the collection
specification and [data_model.md](data_model.md) for what is implemented.

## Runtime

See [app_lifecycle.md](app_lifecycle.md). Start the stack with:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Health: `GET http://127.0.0.1:8001/api/health` (`service: platform`).
