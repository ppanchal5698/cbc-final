# Architecture

CBC Estimating Copilot is a domain-bounded layout:

```
packages/cbc/
  domain/        pure rules (no Mongo, FastAPI, clock, filesystem)
  contracts/     preferred name for Pydantic shapes (schemas/ still works)
  persistence/   repositories, indexes, migrations, envelope
  extraction/    PDF → openings (re-exports from services during rename)
  pricing/       three cost paths + snapshot freezing
  quoting/       estimate versions, proposal, reuse, feedback
  agents/        Claude runtime (worker_kit/ still works)
  platform/      auth, jobs, storage, audit
  http/          FastAPI service factory
services/        thin HTTP adapters via create_service_app()
mcp-servers/     six MCP servers on shared _runtime
apps/web/        Next.js Ops-Hub
```

## Dependency rule

Nothing below imports anything above it. Enforced by `tests/api/test_layering.py`.

```
services/* HTTP  →  cbc.{quoting,pricing,extraction,platform}
                 →  cbc.persistence → cbc.contracts → cbc.domain
```

## Data model

See [collections.mongodb.md](collections.mongodb.md) for the 32-collection
specification and [data_model.md](data_model.md) for what is implemented.

## Runtime

See [app_lifecycle.md](../app_lifecycle.md). Start the stack with:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```
