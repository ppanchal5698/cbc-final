# CBC Estimating Copilot — domain-bounded microservices
#
# This tree is a restructure of cbc-copilot-claude-cli. The original repo is
# untouched. ADR-001 (modular monolith) is superseded here — see
# docs/collections.mongodb.md, app_lifecycle.md, and docs/architecture.md.
#
# Quick start:
#   cp .env.example .env
#   docker compose -f infra/docker-compose.yml up -d --build
#
# Web UI: http://localhost:3000
# Platform API health: http://127.0.0.1:8001/api/health

## Layout

- `packages/cbc` — shared domain kernel (schemas, calc, jobs, storage)
- `services/{platform,intake,extraction,pricing,quoting,catalog}` — APIs + workers
- `apps/web` — Next.js Ops-Hub (BFF routes to domain services)
- `mcp-servers` / `.claude` — Claude Code tools and agents
- `infra/docker-compose.yml` — full stack
- `data/projects`, `data/pricebooks` — runtime volumes (`projects`/`pricebooks` junctions)

## Native API (example)

```powershell
$env:PYTHONPATH = "packages;services/platform"
python -m uvicorn api.main:app --port 8001
```

Domain workers:

```powershell
$env:PYTHONPATH = "packages"
$env:WORKER_DOMAIN = "extraction"
python services/extraction/worker/main.py
```

## Tests

The suite needs a clean virtualenv — a system Python that already carries a
`fastapi`/`starlette` pair from somewhere else will fail collection with
`Router.__init__() got an unexpected keyword argument 'on_startup'`. The MCP
servers' dependencies (`mcp`, `pdfplumber`) come from the `mcp-servers`
distribution, which `requirements.txt` does not pull in:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -e ./mcp-servers   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m pytest -q
```
