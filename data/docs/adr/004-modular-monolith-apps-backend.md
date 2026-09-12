# ADR-004: Modular monolith under apps/backend

## Status

Accepted

## Context

CBC previously ran as six thin FastAPI adapters over a shared `packages/cbc`
kernel. Services did not call each other over HTTP; they shared MongoDB, disk/S3,
and a Mongo job queue. That topology was already a modular monolith deployed as
multiple processes. Rewriting into `apps/backend` collapses deployment without
inventing new domain seams.

ADR-001 already requires a clean new tree and file-by-file migration of logic
(no retyping of calc, matching, freshness, or job lease).

## Decision

1. Build the backend as a **modular monolith** under `apps/backend/src/cbc`.
2. Preserve capability modules: platform, intake, extraction, pricing, quoting,
   catalog, plus shared kernel, jobs orchestration, and agent runtime.
3. Keep **URL prefixes identical** to today's service routers so the web proxy
   can later target one host without rewriting the UI.
4. Keep the legacy tree (`services/*`, `packages/cbc`) running until a later
   cutover phase. Phase 0 is a parallel runnable skeleton only.

## Consequences

- One FastAPI app mounts all module routers; compose runs one claim-all worker.
- Layering tests forbid `modules.X → modules.Y.api` and `shared → modules`.
- Phase 5 cutover completed: compose + web target a single `platform` host.
- Migration filled stubs file-by-file; it did not redesign domain seams.

## Phase 5 (2026-09)

Cutover cleanup completed:

- Compose runs a single API container (`platform` → `apps/backend`).
- Profile-gated legacy `*-api` services were removed from compose.
- Web proxies all paths to `PLATFORM_URL` with JWT audience `platform`.
- Five domain workers were later collapsed to one `worker` (`WORKER_CLAIM_ALL=1`),
  built from `apps/backend/Dockerfile` (`target: worker`).
- Legacy `services/`, `packages/cbc`, root `Dockerfile`, and root `tests/` were
  later moved to `archive/pre-monolith/` (rollback only).

## Worker collapse

Compose no longer starts `intake|extraction|pricing|quoting|catalog-worker`.
A single `cbc-final-worker` claims every job type. Filtered local runs may still
set `WORKER_DOMAIN`.

## CI alignment

`.github/workflows/ci.yml` gates the live path: `apps/backend` pytest,
`apps/web` Node jobs, and compose e2e asserting `platform` / `worker` / `web` /
`mongo`. Archived root tests are not run in CI.

## Native tooling retarget

Root `pyproject.toml` installs `apps/backend/src` (`pip install -e .`).
Workflow scripts set `PYTHONPATH` to `apps/backend/src`.

## Archive

Pre-monolith trees live under [`archive/pre-monolith/`](../../../archive/pre-monolith/).
Restore instructions are in that folder's README. They are not part of the live
compose or install path.

## Cutover complete

Live path is fully cut over:

- Compose: `platform` + claim-all `worker` + `web` (`apps/backend` / `apps/web`)
- CI: `apps/backend` pytest, `apps/web`, e2e; NFR guardrails under `scripts/guardrails/`
- Native install: root `pip install -e .` → `apps/backend/src`
- Rollback: `archive/pre-monolith/` only

API version: `0.10.0-monolith`.

## Docs alignment

Root README, architecture, and folder conventions describe the live
monolith path. Legacy trees are labeled archived.
