# CBC Estimating Copilot — modular monolith

Live runtime is a single FastAPI process under [`apps/backend`](apps/backend)
(compose service name `platform`, port **8001**), plus one worker that claims
all Mongo jobs via `WORKER_CLAIM_ALL=1`.

See [`docs/collections.mongodb.md`](docs/collections.mongodb.md),
[`docs/system-design.md`](docs/system-design.md),
[`docs/data-flow-diagrams.md`](docs/data-flow-diagrams.md), and the phase-by-phase
pipeline docs under [`docs/pipeline/`](docs/pipeline/README.md).

## Quick start

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
```

- Web UI: http://localhost:3000
- API health: http://127.0.0.1:8001/api/health

## Layout

- `apps/backend` — modular monolith: seven modules under `cbc.modules` (see [`docs/system-design.md`](docs/system-design.md)), one API and one worker process
- `apps/web` — Next.js Ops-Hub (proxies `/api` to `PLATFORM_URL`, audience `platform`)
- `infra/docker-compose.yml` — mongo, clamav, platform, worker, web
- `mcp-servers` / `.claude` — Claude Code tools and agents
- `data/projects`, `data/pricebooks`, `data/reference-library` — runtime volumes

## Documentation

- [`docs/system-design.md`](docs/system-design.md) — high-level system structure, services, storage, guardrails, and deployment shape
- [`docs/data-flow-diagrams.md`](docs/data-flow-diagrams.md) — mermaid diagrams for the end-to-end bid flow and artifact handoffs
- [`docs/pipeline/README.md`](docs/pipeline/README.md) — index for the phase-specific pipeline documents
- [`docs/collections.mongodb.md`](docs/collections.mongodb.md) — database schema and provenance model

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

Images build from [`apps/backend/Dockerfile`](apps/backend/Dockerfile).

## Tests

Primary suite (monolith) — also what CI gates:

```bash
cd apps/backend
python -m pip install -e ".[dev]"
pytest
```

CI (`.github/workflows/ci.yml`) runs `apps/backend` pytest, `apps/web`
typecheck/lint/test/build, and Playwright e2e against compose
(`platform` + `worker` + `web`).
