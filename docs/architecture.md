# Architecture

CBC Estimating Copilot runs as a **modular monolith**. The full description - modules,
what each owns, the dependency rule, the seams between modules, and how to add a slice
or a module - is in [ARCHITECTURE.md](../ARCHITECTURE.md) at the repository root.
The decision record is [ADR-005](adr/005-modules-own-their-data.md), which supersedes
[ADR-004](adr/004-modular-monolith-apps-backend.md)'s dependency rule.

```
apps/web  ──►  platform API (apps/backend :8001, cbc.app.main:create_app)  ──►  MongoDB
                      modules/{ops,projects,catalog,intake,extraction,pricing,quoting}
worker (WORKER_CLAIM_ALL=1, python -m cbc.app.worker)  ──►  claim  ──►  Claude CLI + MCP
```

Compose service name for the API remains `platform`; one `worker` claims all job types.
There is no HTTP between modules; API and worker share MongoDB, disk/S3 and the job queue.

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
