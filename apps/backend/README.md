# CBC Backend (modular monolith)

**Live modules:** Platform + Intake + Extraction + Pricing + Quoting + Catalog.
**Workers:** Shared `cbc.worker_kit` via `python -m cbc.worker`
(`WORKER_CLAIM_ALL=1` in compose; `WORKER_DOMAIN` for filtered local runs).

Compose: one API container (`platform` on **8001**, `SERVICE_AUDIENCE=platform`)
and one `worker` from this package's Dockerfile (`target: worker`).
Web proxies all `/api` traffic to `PLATFORM_URL` with JWT audience `platform`.

`archive/pre-monolith/` holds the pre-cutover trees for rollback; they are not
started by the default compose file. CI gates this package's pytest suite.

## Local run

```bash
cd apps/backend
python -m pip install -e ".[dev]"
uvicorn cbc.api.main:app --port 8001
pytest
```

### Worker

```bash
WORKER_CLAIM_ALL=1 python -m cbc.worker --once
WORKER_DOMAIN=catalog python -m cbc.worker --preflight
```

## Stack smoke

From the repo root (restores missing `mcp-servers` from git if needed):

```bash
docker compose -f infra/docker-compose.yml build platform web worker

docker compose -f infra/docker-compose.yml up -d \
  mongo mongo-init clamav platform web worker
```

Expect:

- `GET http://127.0.0.1:8001/api/health` → `200` with `"service":"platform"` and `"status":"ok"`
- App version is `0.10.0-monolith` (OpenAPI / `cbc.api.app`)
- Web at `http://localhost:3000` → `302`/`200`
- Worker logs `worker up - polling` (not a restart loop)

Reference data is copied from `data/reference-library` into the image and mounted
read-only from that path at runtime.
