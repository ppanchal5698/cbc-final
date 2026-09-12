# CBC Estimating Copilot (modular monolith)

Live API + workers: [`apps/backend`](apps/backend). Compose service name
remains `platform` on port 8001. Compose runs one `worker` with
`WORKER_CLAIM_ALL=1` (local runs may still set `WORKER_DOMAIN`).

Web: [`apps/web`](apps/web). Data model: [`docs/collections.mongodb.md`](docs/collections.mongodb.md).
Runtime: [`docs/app_lifecycle.md`](docs/app_lifecycle.md). Architecture:
[`docs/architecture.md`](docs/architecture.md).

Pre-monolith `services/`, `packages/cbc`, root `Dockerfile`, and root `tests/`
are under [`archive/pre-monolith/`](archive/pre-monolith/) for rollback only.

Run: `docker compose -f infra/docker-compose.yml up -d --build`
