# CBC Estimating Copilot (Ops-Hub) Architecture & Lifecycle

> **Live runtime (Phase 5+):** one FastAPI process under `apps/backend`
> (compose service `platform` on port 8001). Web proxies all `/api` traffic to
> `PLATFORM_URL` with JWT audience `platform`. One compose `worker` claims all
> Mongo jobs via `WORKER_CLAIM_ALL=1` using `python -m cbc.worker`. Pre-monolith
> trees are under `archive/pre-monolith/` (rollback only).

## 1. Overview
The CBC Estimating Copilot (Ops-Hub) assists bidding and quoting. The live
backend is a modular monolith (`apps/backend`) plus one headless worker that
invokes the Claude Code CLI. The frontend is Next.js (`apps/web`). API and worker
share MongoDB, disk/S3, and a Mongo job queue — there is no inter-domain HTTP.

## 2. High-Level Architecture Diagram

```mermaid
flowchart TD
    subgraph Frontend
        Web[Next.js Web UI\napps/web]
    end

    subgraph API
        Platform[platform API\napps/backend :8001]
    end

    subgraph Workers
        Worker[worker WORKER_CLAIM_ALL]
    end

    subgraph Storage
        Mongo[(MongoDB)]
        Disk[(Shared Disk Volume\n/app/data)]
    end

    subgraph External
        LiteLLM[LiteLLM Proxy\nLLM Routing]
        Claude[Claude Code CLI\nvia litellm/Anthropic]
    end

    Web -->|PLATFORM_URL aud=platform| Platform
    Platform --> Mongo
    Platform --> Disk
    Worker --> Mongo
    Worker --> Disk
    Worker --> Claude
    Claude --> LiteLLM
```

## 3. Entry Points

| Component | Entry Point File Path | Purpose |
| --- | --- | --- |
| **platform API** | `apps/backend` → `cbc.app.main:create_app` (factory) | FastAPI monolith: seven modules registered by one composition root |
| **Worker** | `python -m cbc.worker` (`WORKER_CLAIM_ALL=1` in compose) | Claim and run Claude / local catalog jobs |
| **Web** | `apps/web` | Next.js Ops-Hub; proxies to `PLATFORM_URL` |
| **Compose** | `infra/docker-compose.yml` | mongo, clamav, platform, worker, web |

Start (Docker):

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Start (native API):

```bash
cd apps/backend && pip install -e ".[dev]" && uvicorn cbc.app.main:create_app --factory --port 8001
```

## 4. Startup Sequence

1. **Infrastructure**: `infra/docker-compose.yml` boots `mongo` (and optional `litellm` / `clamav`).
2. **platform API**: `uvicorn cbc.app.main:create_app --factory` from `apps/backend`.
   - Lifespan runs the migrations, then each module's `ensure_indexes()`, `ensure_readonly_user()`, and ops' OAuth session sweep.
   - Each module's `register(app)` mounts its slices on one FastAPI app (`SERVICE_AUDIENCE=platform`).
3. **Worker**: compose `worker` with `WORKER_CLAIM_ALL=1`; ops' claim loop runs each job with the Claude pipeline `cbc/worker/main.py` binds in (local runs may set `WORKER_DOMAIN`).
4. **Web**: `next start`; `/api/proxy/*` forwards to `PLATFORM_URL` with audience `platform`.

## 5. Core Lifecycle Flows

### Flow 1: HTTP API Request (Sign-in)
1. **Trigger**: User posts credentials via the Next.js UI (`apps/web/app/signin`).
2. **NextAuth**: `apps/web/auth.ts` intercepts via the `Credentials` provider.
3. **Internal Call**: NextAuth calls `${API_BASE}/api/auth/verify` via HTTP.
4. **platform API**: ops' `VerifyCredentials` slice (`cbc.modules.ops`) receives the request.
5. **Database**: Reads ops' `users` collection, compares password hashes, records `authAttempts`.
6. **Response**: User object returned to NextAuth; session JWT issued; redirect to `/dashboard`.

```mermaid
sequenceDiagram
    participant User
    participant NextJS
    participant PlatformAPI
    participant MongoDB
    
    User->>NextJS: Submit Sign-in Form
    NextJS->>PlatformAPI: POST /api/auth/verify (JSON)
    PlatformAPI->>MongoDB: db.users.find_one
    MongoDB-->>PlatformAPI: User Doc + Hash
    PlatformAPI-->>NextJS: User Object (200 OK)
    NextJS-->>User: Issue JWT and Redirect
```

### Flow 2: Queued Job (Document Upload & Extraction)
1. **Trigger**: User uploads a PDF via the web proxy to platform documents API.
2. **Route**: intake's `UploadDocument` slice receives the file.
3. **Storage**: PDF saved under `projects/{slug}/uploads/raw/`.
4. **Enqueue**: Pipeline job (e.g. `extract_bid_set`) queued through `cbc.modules.ops.api.jobs`.
5. **Worker Poll**: compose `worker` (`WORKER_CLAIM_ALL=1`) claims the job.
6. **Execution**: the job slice registered for its type runs it - a headless Claude Code pass (`cbc.modules.ops.api.claude_pass`), or in-process work for the catalog's local jobs.
7. **Heartbeat**: Updates `heartbeatAt` so the job is not reaped.
8. **Sync**: Disk JSON artifacts synced into Mongo.
9. **Orchestration**: Autopilot may enqueue the next phase (e.g. `match_and_price`).
10. **Cleanup**: Job `status="done"`.

```mermaid
sequenceDiagram
    participant UI
    participant PlatformAPI
    participant Disk
    participant MongoDB
    participant Worker
    participant Claude
    UI->>PlatformAPI: POST PDF File
    PlatformAPI->>Disk: Save to /app/data/projects/{slug}/raw/
    PlatformAPI->>MongoDB: Insert job type extract_bid_set
    PlatformAPI-->>UI: 201 Created
    
    Worker->>MongoDB: claim()
    MongoDB-->>Worker: Return queued job
    Worker->>Claude: Invoke Claude CLI pass
    loop Heartbeat
        Worker->>MongoDB: Update heartbeatAt
    end
    Claude->>Disk: Analyze PDF & Write JSONs
    Claude-->>Worker: Exit Code
    Worker->>Disk: Read output JSONs
    Worker->>MongoDB: sync_results() (Save extractions)
    Worker->>MongoDB: finish() (Set status="done")
```

## 6. Module Map

| Module / Package | Responsibility | Key Files |
| --- | --- | --- |
| `apps/web` | Next.js Ops-Hub | proxy, auth, pages |
| `apps/backend` | Live modular monolith API + worker | `cbc.app.main`, `cbc.worker.main`, `cbc.modules.*` |
| `mcp-servers` | Claude MCP tools | per-server `server.py` |
| `archive/pre-monolith/` | Pre-cutover services/packages/Dockerfile/tests | rollback only |

## 7. Data Layer
* **Storage Engines**: MongoDB + shared disk (`/app/data/projects`, `/app/data/pricebooks`).
* **Collections / indexes**: each module's `infrastructure/collections.py` (`ensure_indexes` on boot, after the migrations).
* **Migrations**: `cbc.persistence.migrations` - forward-only, run first at startup.

## 8. Auth & Security Flow
1. NextAuth on `apps/web`.
2. Backend internal JWT (`aud=platform`) or `INTERNAL_API_TOKEN`.
3. Read-only Mongo user for catalog MCP (`ensure_readonly_user`).

## 9. Error Handling & Observability
Worker retry/backoff and `reap_abandoned` in ops' worker loop; the audit trail and run metrics through `cbc.modules.ops.api`.

## 10. Configuration & Environments
Compose injects `MONGODB_URI`, `STORAGE_ROOT`, `PLATFORM_URL` / `API_BASE_URL`, `INTERNAL_*`, `APP_ENV`, `WORKER_CLAIM_ALL`. Settings via `cbc.shared.config`.

## 11. External Integrations
Optional LiteLLM; Claude Code in worker image; MCP under `mcp-servers/`.

## 12. Shutdown & Cleanup
API lifespan cancels background tasks; workers handle SIGTERM/SIGINT; stale jobs reaped.

## 13. Build & Deployment Notes
* Live image: `apps/backend/Dockerfile` (`api` + `worker` targets).
* Root `Dockerfile`: legacy rollback only.
* Compose: `platform` + `worker` + `web` (no live domain `*-api` / `*-worker`).

## 14. Open Questions / Ambiguities
* Prefer `apps/backend/tests` for the live path; archived suites live under
  `archive/pre-monolith/tests/`.
* Agent prompts and sandbox details live under `.claude/` and `cbc.worker_kit`.

## 15. Glossary
* **Autopilot**: A mode where extraction, matching, and pricing are chained automatically without user intervention between steps.
* **Module**: one of seven bounded contexts under `apps/backend/src/cbc/modules/`, each a set of vertical slices that owns its collections; jobs are claimed by the compose claim-all worker (or a filtered `WORKER_DOMAIN` process locally).
* **MCP Server**: Model Context Protocol servers used to give Claude Code structured, read-only tools to view MongoDB data (like price books).
* **Price Book**: A structured catalog of construction materials and their costs.
* **Bid Set**: The PDF architectural drawings uploaded by the user to be quoted.
