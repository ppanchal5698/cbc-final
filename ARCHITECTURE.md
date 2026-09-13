# Architecture

The CBC Estimating Copilot backend (`apps/backend`) is a **modular monolith**: one
API process and one worker process, built from the same package, split inside into
seven modules that each own their data and meet only through small public surfaces.
There are no microservices and no network calls between modules.

```
apps/web ──HTTP──► API process   cbc.app.main:create_app     ──┐
                    seven modules, each registered by the root  ├─► MongoDB, disk/S3
worker process ──► cbc.worker (ops' loop + modules' jobs)     ──┘
```

## The modules

| Module | What it is | Owns (MongoDB) |
|---|---|---|
| **ops** | Running the platform: sign-in and users, system settings, the job queue, the worker loop, the audit trail, spend and run metrics | `users`, `authAttempts`, `oauthSessions`, `settings`, `jobs`, `auditLogs`, `runMetrics` |
| **projects** | The bid record everything hangs off: create/list/update/delete a bid, prior-quote reuse, calls/notes/RFIs logged against it, the autopilot saga | `bidRequests`, `calls`, `counters` |
| **catalog** | Vendor parts and the price books they come from; the jobs that index each book's pages | `catalogItems`, `priceBooks`, `pageIndex` |
| **intake** | Getting a bid set in: document upload, pages, frozen addendum versions | `documents`, `estimateVersions` |
| **extraction** | What the drawings say: openings the estimator confirms or corrects, FRP takeoffs, correction feedback | `openings`, `failedExtractions`, `takeoffs`, `feedbackEvents` |
| **pricing** | Pricing policy: margins, tax, adders, tiers, nets, finishes, frame depths, FRP constants | `referenceData`, `referenceDataRevisions` |
| **quoting** | The customer-facing document: priced lines, totals, alternates, the proposal (which never sends), vendor RFQs, RFIs | `estimateLines`, `quotes`, `proposals`, `vendorRfqs`, `rfis` |

## Layout

```
apps/backend/src/cbc/
  app/main.py              API composition root: middleware, error mapping, health,
                           lifespan (migrate, then each module's indexes), registration
  app/migrations/          forward-only migrations - the one cross-collection code
  worker/main.py           worker composition root: registers every module's jobs into ops' loop
  modules/<module>/
    __init__.py            register(app), ensure_indexes(), register_jobs() - all the roots call
    api/                   the ONLY thing another module may import
    features/<UseCase>.py  one file per use case: route (or job), validation, data access
    domain/                request models and pure rules the module's slices share
    infrastructure/        collections.py (its collections + indexes), shared adapters
  shared/                  config, auth, mongo client + primitives, events, logging,
                           tracing, otel, envfile, pass files, the project file tree (storage,
                           S3, malware scan), manifests, persistence (collection names, the
                           audit envelope, the tenant-scoped repository), PDF reading, the LLM
                           client - no module imports allowed
```

`apps/backend/src/cbc` also still holds the pre-module kernel the modules lean on
(see *Still legacy* below).

## The dependency rule

A module may import another module **only** as `cbc.modules.<other>.api`. Nothing
outside a module - the kernel, the composition roots, MCP servers, scripts - may
import a module's `features`, `domain` or `infrastructure`. `shared` imports no
module. No module names another module's collection. All of this is enforced by
`apps/backend/tests/architecture/test_layering.py`.

Who depends on whom (no cycles):

```
ops         ─ (nothing)
pricing     → ops
projects    → ops
catalog     → ops, pricing
extraction  → ops, projects, pricing, catalog
quoting     → ops, projects, catalog, extraction, pricing
intake      → ops, projects, extraction, quoting
```

When the dependency would point the wrong way, the owner does not get imported -
it gets **plugged in**:

| Seam | Declared by | Supplied by | Wired in |
|---|---|---|---|
| project code → id, bid names for the dead-letter list | `ops.api.project_lookup` | `projects.api.lookup` | `app/main.py` |
| who is an admin | `shared.auth.set_role_lookup` | `ops.api.identity.role_of` | `app/main.py` |
| what runs a claimed job | `ops.api.worker.register` | each module's job slices | each module's `register_jobs`, called by `worker/main.py` |
| what follows any job's end, unless its type says | `ops.api.worker.bind` | `projects.api.pipeline` (`after_pass`, `dead_letter`) | `worker/main.py` |
| a bid's documents, for an extraction pass | `extraction.api.documents` | `intake.api.documents` | intake's `register_jobs` |
| board counts: documents, openings, quotes | `projects.api.board_sources` | intake, extraction, quoting | each module's `register` |

and **events** (`shared/events.py`: in-process, awaited in order, no broker):

| Event | Published by | Handled by |
|---|---|---|
| `ops.job_requeued` | ops `RetryJob` | projects - the bid's saga returns to the job's start state |
| `projects.project_deleted` | projects `DeleteProject` | intake, extraction, quoting - each deletes its own rows |

Typed errors stay transport-free and the root maps them: `ops.api.jobs.PipelineJobActive`
→ 409, `projects.api.lookup.ProjectNotFound` → 404, `ValueError` → 400.

## Adding a slice

1. Create `modules/<module>/features/<UseCase>.py` with its own
   `router = APIRouter(prefix=..., tags=[...])`, its request model, and its handler.
   Read and write only your module's collections (`infrastructure/collections.py`).
2. Add it to the tuple in `modules/<module>/__init__.py:register`. Order matters only
   where paths overlap: literal paths before `{param}` paths.
3. Need another module's data? Import `cbc.modules.<other>.api`. If it has no port
   for what you need, add a small, named one there - not a generic query.
4. Test it: `tests/characterization` pins every endpoint's status and shape;
   `REQUIRE_MONGO=1 pytest` must stay green, and `test_layering` must pass.

## Adding a job

A job type runs as a slice in the module that owns what it writes.

| Job | Slice |
|---|---|
| `extract_bid_set`, `rerun_extraction` | extraction `ExtractBidSet` |
| `match_and_price` | quoting `MatchAndPrice` - it writes quote lines and the quote, and pricing may not import quoting |
| `build_proposal` | quoting `BuildProposal` |
| `ingest_addendum` | intake `IngestAddendum` |
| `run_full_pipeline` (retired; queued rows still run) | intake `RunFullPipeline` - the one module that may import every part it touches |
| `ingest_pricebook`, `index_catalog`, `delete_catalog` | catalog `IngestPricebook`, `IndexCatalog`, `DeleteCatalog` |

1. Create `modules/<module>/features/<JobName>.py` with `async def run(job)`. A Claude
   pass over a bid calls `projects.api.pipeline.run_pass(job, sync=..., prepare=..., watch=...)`,
   and its `sync` starts with `extraction.api.passes.check_output`; a pass with no bid
   calls `ops.api.claude_pass.run`; in-process work goes through `ops.api.worker.run_locally`.
2. Register it in the module's `register_jobs()`. Pass `after_finish=` only when the job
   has more to do when it ends than `projects.api.pipeline.after_pass`.
3. Declare the type in `JobType` (ops' `domain/jobs.py`). A Claude pass needs a template
   in `cbc.worker_kit.prompts`, and every job type a
   domain in `DOMAIN_JOB_TYPES` (ops' `WorkerLoop`); `tests/pipeline/test_toolset_registry.py` fails
   on a job type nothing runs.

## Adding a module

1. `modules/<name>/{__init__,api/__init__,features/__init__,domain/__init__,infrastructure/__init__}.py`.
2. `infrastructure/collections.py`: one accessor per owned collection (names from
   `cbc.shared.persistence.names`) and `ensure_indexes()`.
3. `__init__.py`: `register(app)` and `ensure_indexes()`; `register_jobs()` too if it runs
   jobs, and add it to `wire()` in `worker/main.py`.
4. In `app/main.py`: import it, call `register` in `create_app`, and add its
   `ensure_indexes` to `migrate_and_index` (after the migrations).
5. Decide where it sits in the dependency graph above before its first import.

## Data

One Motor client (`shared/mongo.py`), one database, per-module collections and
indexes. Migrations (`cbc/app/migrations`) are forward-only, run once at
startup before any module's indexes, and are the one deliberate cross-collection
exception - they rename and backfill across modules. The catalog MCP server gets a
connection that cannot write: `shared/mongo.py` derives it (`readonly_uri`), and
startup creates the user behind it (`ensure_readonly_user`).

## What is not a module

Everything under `cbc/` is a module, `shared/`, or a composition root (`app/`,
`worker/`) - except `cbc.worker_kit`, a Claude pass's prompt templates and its
sandbox. It sits above the modules on purpose: building a pass's prompt reads
catalog's match cache while ops' Claude pass calls it, so no module could hold it
without a cycle. `workflows/*.sh`, CI and the sandbox image also run it by module
path.

The pre-module kernel is gone: `cbc.db`, `services`, `schemas`, `pageindex`,
`persistence`, `domain`, `core` and `validation` went into the modules, `shared/`
and `app/`, and `test_layering` fails if any of them comes back.

## Known inconsistencies (recorded, not resolved)

- RFIs live in two places: `rfis` (quoting) and `calls` with `kind="rfi"` (projects).
  Neither is authoritative; merging them changes behaviour.
- `DELETE /api/users/{id}` and `DELETE /api/projects/{code}/quote/lines/{id}` answer
  200, every other delete 204.
- Out-of-scope products (`.claude/rules/scope-boundaries.md`) are documented, not enforced.
- `projects.api.lookup.load` returns the stored bid document rather than a typed
  reference; it narrows once its readers are sliced.
