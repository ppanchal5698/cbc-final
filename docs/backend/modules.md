# Backend modules

The backend is one FastAPI process (`apps/backend`, compose service `platform`,
port 8001) split into seven modules under `apps/backend/src/cbc/modules/`. There
is no shared kernel: each module owns its own collections, its own rules and its
own routes, and reaches the others only through their published `api/`.

This document describes what each module owns and the boundary rules that keep
them separable. Those rules are not conventions — every one of them is executed
as a test in `apps/backend/tests/architecture/test_layering.py`, so breaking one
fails the build rather than the review.

---

## The four layers

Every module has the same internal shape:

| Directory | Holds | May be imported by |
|---|---|---|
| `api/` | the module's published surface — the functions and types other modules are allowed to call | anything |
| `features/` | one file per use case, PascalCase, each exporting a FastAPI `router` or a job handler | that module only |
| `domain/` | pure rules and calculations, no I/O | that module only |
| `infrastructure/` | Mongo collections and outward adapters | that module only |

`__init__.py` is the module's entry point and exposes some subset of
`register(app)`, `register_jobs()`, `ensure_indexes()` plus module-specific
extras. `apps/backend/src/cbc/app/main.py` calls `register`;
`apps/backend/src/cbc/app/worker.py` calls `register_jobs`.

## What each module owns

Collection constants are declared in each module's
`infrastructure/collections.py` and spelled once in
`apps/backend/src/cbc/shared/persistence/names.py`. Every collection's fields
and indexes are specified in [`../collections.mongodb.md`](../collections.mongodb.md).

| Module | Responsibility | Collections owned |
|---|---|---|
| **ops** | Running the platform: auth, users, audit, spend, the job queue and the worker loop, Claude provider config | `users`, `authAttempts`, `auditLogs`, `runMetrics`, `settings`, `oauthSessions`, `jobs` |
| **projects** | The bid record everything else hangs off, plus the autopilot state machine | `bidRequests`, `calls`, `counters` |
| **pricing** | Pricing policy only — margin bands, tax, adders, vendor tiers, special nets, finishes, frame depths, FRP constants | `referenceData` |
| **catalog** | Parts and vendor price books, page indexing, match learning | `catalogItems`, `priceBooks`, `catalogPages`, `multiplierPages`, `matchLearning`, `pageIndex` |
| **extraction** | Openings, alternates, FRP and Div 10 take-offs, estimator corrections | `openings`, `failedExtractions`, `takeoffs`, `feedbackEvents` |
| **quoting** | Priced lines, totals, the proposal, vendor RFQs and RFIs. Renders and routes, never sends | `estimateLines`, `quotes`, `proposals`, `vendorRfqs`, `rfis` |
| **intake** | Document upload, page render, MinerU parse, addendum versions | `documents`, `documentPages`, `estimateVersions` |

`pageIndex` is the one exception to the pattern: it is owned by
`catalog/api/pageindex/store.py` rather than by `collections.py`.

## The dependency graph

Derived from the actual `import` statements, not from intent:

```
ops       →  (nothing)
projects  →  ops
pricing   →  ops
catalog   →  ops, pricing
extraction→  catalog, ops, pricing, projects
quoting   →  catalog, extraction, ops, pricing, projects
intake    →  extraction, ops, projects, quoting
```

`ops` sits at the bottom and imports no other module — it is the platform every
other module runs on. **`intake` sits at the top**, which reads as a surprise:
"upload a PDF" depending on quoting. Both edges are deliberate.

`intake/infrastructure/snapshot.py` freezes a bid's openings *and quote lines*
into an addendum version, so it needs `quoting.api.lines` by definition.

`intake/features/RunFullPipeline.py` backs the retired `run_full_pipeline` job.
`POST /api/jobs` refuses it, but a job queued before it was retired still runs,
and it is placed here precisely because intake is the one module permitted to
import every part it touches. `WorkerLoop._CLAIM_ALL_EXTRA` keeps that job type
claimable for the same reason. Two places support it on purpose — deleting the
feature would strand a requeued historical job.

The graph is acyclic, and that is checked two ways: by
`test_the_module_graph_has_no_cycles`, and independently by the knowledge-graph
build in `graphify-out/GRAPH_REPORT.md`, which reports no import cycles across
the whole repository.

### Downward dependencies are inverted with explicit ports

A lower module never imports a higher one. When `ops` needs to know a project's
name, the higher module hands it a function at startup. There is no DI
container; the wiring is a `bind(...)` call you can grep for:

- `ops/api/project_lookup.bind`
- `ops/api/worker.bind` and `bind_parse_status`
- `projects/api/board_sources.bind_document_counts`, `bind_opening_counts`, `bind_quotes`
- `extraction/api/documents.bind`
- `pricing/api/catalog_baseline_backfill.bind_catalog_lookup`

The types that cross these ports are pinned by
`tests/architecture/test_port_types.py`: every document-returning port names a
TypedDict (`ProjectRef`, `JobRef`, `ProductRef`, `OpeningRef`, `QuoteTotals`)
and no module may read a field the owning type does not declare.

### Events

For fire-and-forget notification there is a small in-process bus,
`apps/backend/src/cbc/shared/events.py` (37 lines, subscribers awaited in
order). Five topics:

`projects.project_deleted` · `intake.version_snapshot_requested` ·
`quoting.quote_completed` · `extraction.lines_confirmed` · `ops.job_requeued`

## The boundary rules

All seven are enforced by `tests/architecture/test_layering.py`.

1. **Modules reach each other only through `api/`.** Inside
   `src/cbc/modules/<m>/`, an import resolving to `cbc.modules.<other>.<sub>`
   is an error unless `<sub>` is `api`. The check also synthesises
   `from cbc.modules.x import features` into the same form, so aliasing does not
   evade it.
2. **Nothing outside a module touches its insides.** Everything in `src/cbc`
   outside `modules/`, plus `mcp-servers/` and `apps/backend/scripts/`, may not
   import any module's `features`, `domain` or `infrastructure`. Tests are
   exempt because they are not scanned.
3. **`shared` imports no module.** Nothing under `src/cbc/shared/` may import
   `cbc.modules` or anything beneath it.
4. **No module names another module's collection.** Ownership is derived by
   AST-scanning each `infrastructure/collections.py`; a constant declared twice
   is an error. Both `names.X` attribute access and raw string subscripts
   (`db["catalogItems"]`) are checked.
5. **The retired kernel stays retired.** None of `db.py`, `services`, `schemas`,
   `pageindex`, `persistence`, `domain`, `core`, `validation`, `http`, `api`,
   `worker` may reappear beside `modules/`, and nothing may import
   `cbc.<any of those>`.
6. **The domain job map covers exactly the expected domains** —
   `WorkerLoop.DOMAIN_JOB_TYPES` keys are exactly
   `{intake, extraction, pricing, quoting, catalog, parsing}`.
7. **No cycles** in the module graph.

Rule 1 has a deliberate carve-out for composition: `catalog.register` imports
`pricing.api.catalog_baseline_backfill` and `extraction.register` imports
`projects.api.board_sources`. Both are `.api` so they pass, but the effect is
that some wiring lives in module `__init__.py` files as well as in
`apps/backend/src/cbc/app/`.

### Companion contracts

Three more tests in the same directory guard things a layering check cannot see:

- `test_composition_root.py` — spawns a subprocess and asserts
  `cbc.shared.config` was **not** yet imported when `envfile.apply_to_environ`
  ran, for both `cbc.app.main` and `cbc.app.worker`. See
  [`api.md`](api.md#the-import-order-that-matters).
- `test_confidence_floor.py` — the literal `0.75` may be written only in
  `pricing/api/confidence.py`. It also reaches across into
  `apps/web/components/extraction/line-item-row.tsx` and asserts the web row
  uses the same number.
- `test_imports_resolve.py` — resolves every deferred and function-body import
  name, which is what catches a rename that only breaks on a rarely-taken path.

## The shared layer

`apps/backend/src/cbc/shared/` is 22 modules plus `persistence/`. It imports no
module (rule 3). The load-bearing ones, by how many files import them:

| Module | Imports | What it is |
|---|---|---|
| `mongo.py` | 91 | The single lazy Motor client. `database()`, `oid()`, `serialise()`, `run_transaction`, `readonly_uri()`, and the two index helpers every `collections.py` depends on — `create_index_resilient` (survives `IndexOptionsConflict` from legacy auto-named indexes) and `replace_index` |
| `auth.py` | 75 | `InternalAuthMiddleware`, `get_actor`, `require_admin`, `PUBLIC_PATHS`, and `set_role_lookup` |
| `paths.py` | 25 | `repo_root()`, `storage_root()`, `pricebook_dir()`, `reference_dir()` — asked once instead of counted with `parents[N]` in eleven places |
| `persistence/` | 20 | `names.py` (every collection name, once), `envelope.py` (`stamp_new`/`stamp_update`/`soft_delete`/`alive`), `repository.py` (injects `orgId` into every query) |
| `config.py` | 18 | The frozen `Settings`, read from `os.environ` **once at import** |
| `pass_files.py` | 11 | `read_json`/`write_json`/`distinct_keys` for reading back what a Claude pass wrote |

Smaller but architecturally significant: `events.py` (above), `logs.py`
(`JsonFormatter`, `bind`), `tracing.py` (`TraceMiddleware`, `X-Trace-Id`
propagated into enqueued jobs), `manifests.py` (artifact sidecars and
`reusable_phases`, the phase-handoff mechanism), `storage.py` (project tree
layout, `receive_upload`, `atomic_write_*`), and the PDF family
(`pdfcheck`/`pdfpages`/`pdfrows`/`pdftext`).

## Where to go next

- How the routes are assembled and what runs at startup: [`api.md`](api.md)
- How a job is claimed, run and retried: [`worker.md`](worker.md)
- What every collection contains: [`../collections.mongodb.md`](../collections.mongodb.md)
