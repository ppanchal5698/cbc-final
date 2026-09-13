# ADR-005: Modules own their data and meet only through their api

## Status

Accepted. Supersedes ADR-004's dependency rule; its deployment decisions stand.

## Context

ADR-004 collapsed six services into one process but kept their shape: thin route
folders under `modules/` over a shared kernel (`services`, `schemas`, `db`) that
every route reached into directly. Its layering test forbade `modules.X` importing
`modules.Y.api` - the one import a modular design should allow - while permitting
every route to read any collection. In practice one handler could touch four
collections owned by three domains, and deleting a bid cascaded by naming seven.

## Decision

1. Seven modules - ops, projects, catalog, intake, extraction, pricing, quoting -
   each owning its collections and indexes (`infrastructure/collections.py`).
2. Inside a module, vertical slices: one `features/<UseCase>.py` per endpoint or job.
3. A module imports another only through `cbc.modules.<other>.api`; nothing outside a
   module imports its insides; `shared` imports no module; no module names another's
   collection. Enforced by `tests/architecture/test_layering.py`.
4. Where a dependency would form a cycle, the owner is plugged in (bound ports in
   `ops.api.project_lookup`, `ops.api.worker`, `projects.api.board_sources`) or told
   (`shared/events.py`: `ops.job_requeued`, `projects.project_deleted`).
5. One composition root per process (`cbc/app/main.py`, `cbc/worker/main.py`)
   registers modules, binds ports and maps typed errors to HTTP.
6. URLs, methods, status codes, bodies, auth, the database and its collection names
   are unchanged. `tests/characterization` pins all 124 routes.

## Consequences

- The legacy kernel remains beneath the modules; each module import of `cbc.db` or
  `cbc.services` is marked with where it goes, and the test rejects unmarked ones.
- Two placements differ from the rewrite plan, because the plan's would have formed
  cycles: `StartAutopilot` lives in projects (it moves the bid's saga), and the
  alternates slices live in quoting (they roll up quote lines and totals).
- The worker's startup log no longer prints the runner's per-job budgets; ops' loop
  cannot import the runner to read them.
- See [ARCHITECTURE.md](../../ARCHITECTURE.md) for the rules, the seams and how to add
  a slice or a module.
