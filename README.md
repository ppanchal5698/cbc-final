# CBC Estimating Copilot — modular monolith

Live runtime is a single FastAPI process under [`apps/backend`](apps/backend)
(compose service name `platform`, port **8001**), plus one worker that claims
all Mongo jobs via `WORKER_CLAIM_ALL=1`.

See [`docs/collections.mongodb.md`](docs/collections.mongodb.md),
[`docs/app_lifecycle.md`](docs/app_lifecycle.md), and
[`docs/architecture.md`](docs/architecture.md). The module map and its rules are in
[`ARCHITECTURE.md`](ARCHITECTURE.md); decision records
[`ADR-004`](docs/adr/004-modular-monolith-apps-backend.md) and
[`ADR-005`](docs/adr/005-modules-own-their-data.md).

## Quick start

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
```

- Web UI: http://localhost:3000
- API health: http://127.0.0.1:8001/api/health

## Layout

- `apps/backend` — modular monolith: seven modules under `cbc.modules` ([`ARCHITECTURE.md`](ARCHITECTURE.md)), one API and one worker process
- `apps/web` — Next.js Ops-Hub (proxies `/api` to `PLATFORM_URL`, audience `platform`)
- `infra/docker-compose.yml` — mongo, clamav, platform, worker, web
- `mcp-servers` / `.claude` — Claude Code tools and agents
- `data/projects`, `data/pricebooks`, `data/reference-library` — runtime volumes
- `archive/pre-monolith/` — **rollback only** (`services/`, `packages/`, root `Dockerfile`, root `tests/`)

## Native API (local)

From the repo root, `pip install -e .` installs the monolith (`apps/backend/src`).
Prefer the package-local editable install when developing the API alone:

```bash
cd apps/backend
python -m pip install -e ".[dev]"
uvicorn cbc.app.main:create_app --factory --port 8001
```

Worker (compose uses claim-all; filter locally if needed):

```bash
WORKER_CLAIM_ALL=1 python -m cbc.app.worker
# or: WORKER_DOMAIN=catalog python -m cbc.app.worker --once
```

Root [`Dockerfile`](archive/pre-monolith/Dockerfile) builds the pre-cutover
`packages/` + `services/*` layout and is **rollback-only** (archived); live
images use [`apps/backend/Dockerfile`](apps/backend/Dockerfile).

## Tests

Primary suite (monolith) — also what CI gates:

```bash
cd apps/backend
python -m pip install -e ".[dev]"
pytest
```

CI (`.github/workflows/ci.yml`) runs `apps/backend` pytest, `apps/web`
typecheck/lint/test/build, and Playwright e2e against compose
(`platform` + `worker` + `web`). Archived root `tests/` under
`archive/pre-monolith/tests/` are **not** gated.
