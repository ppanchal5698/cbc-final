# The HTTP API

91 paths, 132 operations, all under `/api`. This document is about how they get
there and what happens around them — the assembly, the startup order and the
cross-cutting behaviour. For what any individual endpoint accepts, read its
feature file; the module tables below say which directory to open.

## There is no app object

`apps/backend/src/cbc/app/main.py` exports a **factory**, not a module-level
ASGI app:

```bash
uvicorn cbc.app.main:create_app --factory
```

The `cbc-api` console script calls `main.run()`, which serves on `0.0.0.0:8001`
with reload off. `create_app(*, background: bool = True)` imports FastAPI inside
the function body; passing `background=False` skips the periodic tasks, which is
how the test harness gets a real app without a scheduler (it used to
re-implement the factory instead, and drifted).

Three constants describe the service: `NAME = "platform"` — the compose service
name, the log and trace name, and what `/api/health` reports as `service` —
`TITLE = "CBC Estimating Copilot API"` and `VERSION = "0.10.0-monolith"`.

### The import order that matters

The first lines of `main.py` are load-bearing and marked `# noqa: E402`:

```python
from cbc.shared import envfile, logs
from cbc.modules.ops.api.provider import MANAGED
envfile.apply_to_environ(skip=MANAGED)     # line 31
from cbc.shared.config import settings     # only now
```

`settings` reads `os.environ` **once, at import**. If anything imports
`cbc.shared.config` before `apply_to_environ` runs, the `.env` file is silently
ignored and the process comes up with defaults. `apps/backend/src/cbc/app/worker.py`
has the same requirement, and
`apps/backend/tests/architecture/test_composition_root.py` enforces both by
spawning a subprocess with a spy on `apply_to_environ` and asserting
`cbc.shared.config` was not yet in `sys.modules` when it fired.

## Routing

There is no router include tree in `app/`. `create_app` calls each module's
`register(app)`, and each module includes its own routers from its
`features/`:

```python
projects.register(app)   intake.register(app)     extraction.register(app)
pricing.register(app)    quoting.register(app)    catalog.register(app)
ops.register(app)
```

**Registration order is significant**, because FastAPI matches routes in the
order they were added. Two places depend on it, both commented in the source:

- `modules/ops/__init__.py` registers `ListJobs`, `JobMetrics` and
  `ListDeadJobs` **before** `GetJob` — otherwise `/api/jobs/metrics` matches
  `/api/jobs/{job_id}` and `metrics` is read as an id.
- `modules/pricing/__init__.py` registers `DeleteEntry` last, because its
  pattern is a catch-all that would otherwise shadow its siblings.

### Paths by module

| Prefix | Paths | Module | Feature directory |
|---|---|---|---|
| `/api/projects/…` | 45 | projects, extraction, quoting, intake | the bid record and everything hanging off it — documents, openings, takeoffs, lines, proposal, versions |
| `/api/reference/…` | 13 | pricing | margins, tax, adders, tiers, nets, finishes, frame depths, FRP constants |
| `/api/settings/…` | 9 | ops | Claude provider, parsing, pipeline, freshness |
| `/api/jobs/…` | 8 | ops | queue: list, metrics, dead letter, get, create, cancel, retry, terminal (+ SSE stream) |
| `/api/price-books/…` | 4 | catalog | upload, list, file, mark reviewed |
| `/api/users/…` | 3 | ops | list, create, update/delete |
| `/api/catalog/…` | 2 | catalog | product search |
| `/api/auth/…` | 2 | ops | `verify` (what the web tier posts to) and `me` |
| `/api/learning`, `/api/audit`, `/api/ops/…`, `/api/integrations` | 1 each | catalog, ops | match learning, audit log, spend, integration status |
| `/api/health` | 1 | — | see below |

The authoritative list is one command:

```bash
python -c "from cbc.app.main import create_app; print(*create_app().openapi()['paths'], sep='\n')"
```

CI runs a variant of it as a smoke test, so a module that fails to import is
caught before any test does.

## Middleware, auth and errors

Three middlewares, added in this order:

```python
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(InternalAuthMiddleware)
app.add_middleware(TraceMiddleware)
```

Starlette runs the **last added outermost**, so a request passes through
tracing, then auth, then CORS. `TraceMiddleware`
(`cbc/shared/tracing.py`) mints or forwards `X-Trace-Id` and puts it in a
contextvar that survives into enqueued jobs, which is how a job's logs can be
tied back to the request that created it.

`InternalAuthMiddleware` (`cbc/shared/auth.py`) is the trust boundary between
the web tier and the API. It reads `PUBLIC_PATHS` for the unauthenticated
exceptions and resolves the actor's role through `set_role_lookup`, which
`create_app` binds to `identity.role_of` — the inversion that lets `shared`
check roles without importing a module.

Typed domain errors are mapped to status codes in one place, so features raise
and never build a `HTTPException`:

| Exception | Status |
|---|---|
| `ValueError` | 400 |
| `ops_jobs.PipelineJobActive` | 409, detail from `ops_jobs.conflict_detail` |
| `projects_lookup.ProjectNotFound` | 404 |

## Startup

The lifespan context runs, in order:

1. `otel.configure` — a no-op unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
2. `migrate_and_index()` — **migrations first**, then indexes per module in a
   fixed order (ops, projects, catalog, intake, extraction, quoting, pricing).
   The order is not cosmetic: an index built before `m001`'s rename lands on the
   wrong collection.
3. `pageindex_store.ensure_indexes()` — `catalog`'s `pageIndex` is indexed
   separately because it is owned outside `collections.py`.
4. `ensure_readonly_user()` — warns rather than failing, because a missing
   read-only Mongo user degrades the MCP servers but should not stop the API.
5. Background tasks spawn. On shutdown they are cancelled and drained.

Migrations live in `apps/backend/src/cbc/app/migrations/`:
`m001_rename_to_specification`, `m002_audit_envelope`,
`m003_operational_collections`, `m004_opening_door_identity`,
`m005_reference_spine`.

`_forever(job, every, log)` wraps each periodic task. There is exactly one today:
`ClaudeOAuth.sweep_oauth_sessions`, every `OAUTH_SWEEP_SECONDS` (60).

## `/api/health`

The only route no module owns — it is defined inline in `create_app`. It pings
Mongo with a 3-second timeout and reports `status`, `service`, `database`,
`storageRoot` and `sends`, merging in `catalogIndex: ready | missing`. A failure
inside the catalog probe becomes an `extraError` field rather than taking the
whole health check down, so a missing catalog index does not make compose
consider the service unhealthy.

This is the endpoint compose polls (`x-api-health`) and the one CI waits on
before running Playwright.

## How responses are pinned

`apps/backend/tests/characterization/` pins the **shape** of every API response
— keys and JSON types, with ObjectIds and ISO timestamps reduced to markers —
into `snapshots/<module>.json`. Snapshots are only written under
`UPDATE_SNAPSHOTS=1`, so a new test cannot record itself green in CI.

`test_contract.py` is the cross-cutting one. It derives the full route table
from the live app and pins method, path, status and admin-only for each
operation; calls every non-public operation with a bad token and every admin
route as an estimator, recording whatever comes back rather than asserting a
particular code; and asserts that **every operation has at least one real
response pinned by some module recipe**. Adding a route without a
characterization test fails that assertion.

## See also

- Module boundaries and what each one owns: [`modules.md`](modules.md)
- The job queue behind `/api/jobs`: [`worker.md`](worker.md)
- Collection fields and indexes: [`../collections.mongodb.md`](../collections.mongodb.md)
