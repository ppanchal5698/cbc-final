# The Ops-Hub frontend

`apps/web` — Next.js 16 App Router, React 19, Tailwind v4, SWR, NextAuth 5.
It is a consumer of pipeline state, never the source of truth for a
calculation. Every number it shows was computed by the backend.

> Next 16 renamed two things this app relies on: `middleware` became `proxy`,
> and `error.tsx`'s `reset` prop became `retry`. Both are used here. An
> `AGENTS.md` written by `next dev` warns about it.

## Routes

**Root shell** — unauthenticated.

| Path | File | What it is |
|---|---|---|
| `/` | `app/page.tsx` | a five-line `redirect("/dashboard")` |
| `/signin` | `app/signin/page.tsx` | split-screen panel plus `SignInForm` |
| — | `app/layout.tsx` | `<html data-theme="dark">`, Manrope, a pre-paint inline theme script, `<Toaster>` |
| — | `app/global-error.tsx` | root-layout failure; renders its own `<html>` with inline styles, because no stylesheet is available |
| `/api/auth/*` | `app/api/auth/[...nextauth]/route.ts` | three lines, re-exports `handlers` |
| `/api/proxy/*` | `app/api/proxy/[...path]/route.ts` | the backend proxy — see [Data](#data) |

`/signin` is `force-dynamic` deliberately: it was statically prerendered once,
which baked the seed credentials into `signin.html`.

**The guard** is `proxy.ts` (not `middleware.ts`). Anonymous → `/signin`,
signed-in on `/signin` → `/dashboard`. Its matcher **deliberately excludes
`api/proxy`**, so a client fetch gets a real 401 instead of a 200 carrying
sign-in HTML.

**`(app)` group** — authenticated. `app/(app)/layout.tsx` calls `auth()`,
redirects without a session, fetches the rail badge counts (price books and dead
jobs, each in its own try/catch so an outage is reported on the page rather than
breaking the nav), and renders the skip link, the `.app-shell` div, `<Rail>`,
`{children}` and `<ShellOverlays>`.

| Route | Screen |
|---|---|
| `/dashboard` | your queue (flagged → active job → rest), plus pipeline-by-stage, win/loss, due next, estimator load, bid-to-order and value-by-programme panels |
| `/bids` | the bid board — server-side `?stage=` and `?q=`, search, `NewBidDialog` |
| `/bids/[code]` | redirects to `project.stage`, defaulting to `intake` |
| `/bids/[code]/intake` | upload, start-from-prior, versions, and the job record with per-field PDF provenance |
| `/bids/[code]/extraction` | `ExtractionClient`, documents, latest job |
| `/bids/[code]/quote` | `QuoteClient` — priced lines |
| `/bids/[code]/proposal` | `ProposalClient` |
| `/catalog` | product search |
| `/price-books` | price-book and multiplier programs, with staleness |
| `/ops/dead-letter` | dead-letter queue with retry |
| `/ops/spend` | LLM cost against worker claim caps; admin-only at the API |
| `/settings` | branches on role — admins get Claude, parsing and admin panels; estimators get integrations and a pointer to their admin |

Boundaries: `(app)/error.tsx` (uses `retry`; surfaces `error.message` and
`error.digest`), `(app)/loading.tsx`, `(app)/bids/[code]/loading.tsx` (a skeleton
that includes the stage bar), two `not-found.tsx` files sharing
`components/shell/not-found-view.tsx`, and `(app)/[...slug]/page.tsx` — a
six-line catch-all calling `notFound()` so an unmatched route renders the
branded 404 **inside** the shell rather than the bare Next one.

Every `(app)` page is `export const dynamic = "force-dynamic"`.

## Data

Two paths, deliberately separate.

**Server → API.** `lib/api.ts` is `server-only` and exports `api = { get }` —
**read-only by design**. Every write goes through the proxy. It normalises the
`/api/` prefix, sets `cache: "no-store"`, and turns an unreachable API into a
503 `ApiError` that says "Start the stack with docker compose up -d" rather than
a stack trace.

**Browser → API.** `app/api/proxy/[...path]/route.ts` exports all five methods,
all delegating to one `proxy()` function that:

- checks `auth()`, 401 if absent;
- runs `rejectUnsafeProxySegments` then `buildProxyTarget` (`lib/proxy-path.ts`)
  — blocks `..` and encoded separators, then asserts the normalised path still
  starts with `/api/`;
- copies query params **except `actor`**, so a client cannot spoof identity;
- allow-lists request and response headers rather than forwarding everything;
- mints or forwards `X-Trace-Id`;
- rebuilds multipart bodies through `FormData` so the boundary is regenerated;
- maps a client abort to HTTP 499 and streams the upstream body back.

**Credentials.** `lib/internal-api.ts` (`server-only`). With
`INTERNAL_AUTH=token` it sends `X-Internal-Token` and `X-Actor`; with `jwt` it
mints a 60-second HS256 token, `aud: "platform"`, `iss: "cbc-web"`.
`assertProductionSecrets()` fails closed at runtime but skips during the build
phase.

**Client fetchers.** `lib/proxy-fetcher.ts` is the one chokepoint:
`proxyFetcher<T>` (the SWR fetcher), `proxyMutate<T>` (every write),
`proxyFetch` (raw, for PDFs and SSE), `errorMessage`, and
`handleExpiredSession(status)` — which on a 401 does a **full-document**
`window.location.assign`, not `router.push`, because a soft navigation would
keep every stale SWR cache alive.

**SWR.** There is no global `SWRConfig`; every call passes `proxyFetcher`
explicitly. Three polling idioms:

| Idiom | Where |
|---|---|
| function `refreshInterval` keyed on the data (4s while running, 0 otherwise) | `hooks/use-pipeline-job.ts`, `upload-panel`, `price-books-client`, `proposal-client` |
| boolean-gated constant | `extraction-client`, `quote-client` |
| fixed | `terminal-drawer` 5s, `queue-metrics-panel` 15s, `spend-ops-panel` 30s |

Conditional keys (`open ? url : null`) keep work from starting until a panel
opens or a bid is chosen. `router.refresh()` runs alongside `mutate()` wherever
a mutation also changes server-rendered data.

**Types.** `lib/types.ts` is ~1,070 lines and ~75 interfaces, **hand-mirrored
from the backend with no codegen and no shared package**. The comments cite
backend files and spec IDs directly. It is the largest drift risk in the app.

## Domain logic in the client

Some rules necessarily exist on both sides. The distinction that matters is
whether the client *derives* or merely *reads*:

| File | What it does | Duplication |
|---|---|---|
| `lib/board.ts` | `boardStatus(project)` — the one "what state is this bid in" derivation, order-sensitive: shelved > closed > sent > active job > flags > stage. Plus `PIPELINE_STAGES`, `outcomeCounts` (win rate excludes not-bid from the denominator), `dueLabel`, `groupBy` | derived client-side; the API sends no status |
| `lib/margin.ts` | `isBelowBand(line)` reads `line.marginCheck.flag` — **the API's verdict, not re-derived**. The comment records that the flag used to be dropped at the UI boundary | none, deliberately |
| `lib/rfq.ts` | the vendor-RFQ and RFI state machines | **mirrored** from `quoting/domain/rfqs_and_rfis.py` — drift risk if the API adds an edge |
| `lib/slot.ts` | `slotOf(description)`, 13 slots, most-specific-first so "door sweep" resolves to SWEEP | presentation only; never used for pricing or matching |
| `lib/job-error.ts` | `classifyJobError` — prefers the persisted `errorCode`, falls back to substring matching; `translateJobError(error, role)` gives estimators an action and admins a technical hint | heuristics mirror worker error strings |
| `lib/claude-stream.ts` | 662 lines parsing `claude --print --output-format stream-json` into a `LogEntry` union | mirrors the CLI event schema |
| `lib/run-pill.ts` | `runPillFor(job, …)`, kept out of a `"use client"` module so server pages can call it | job-type labels overlap `job-error.ts` |

> **Board status is derived in three places that can disagree**: the canonical
> `boardStatus()` in `lib/board.ts`, `statusOf()` in
> `components/bids/board-groups.tsx:40`, and `waitingOn()` in
> `app/(app)/dashboard/page.tsx:39` — the last redeclaring a local `blocked` set
> that duplicates `BLOCKED_CHAIN` in `lib/run-pill.ts`. The header of
> `lib/board.ts` claims the board and dashboard "can never disagree"; as written
> they can.

**Hooks.** `use-pipeline-job` (`isPipelineJob` + polling), `use-job-recording`
(replay then `EventSource` — the app's only SSE consumer), `use-dialog`
(Escape, focus trap and restore for the four hand-rolled overlays),
`use-debounced`, `use-row-keys` (J/K/Enter/Space/O/Esc, inert while typing).

## Tests

**Vitest** — 19 files, jsdom. Domain (`board`, `slot`, `margin`, `rfq`,
`job-error`, `tax-display`, `format`, `initials`, `claude-stream`), security
(`proxy-path` traversal and encoded separators, `proxy-fetcher` 401 handling,
`internal-api` build-phase skip versus runtime fail-closed, `dev-auth` fails
closed when `APP_ENV` is unset), and components (`rail`, `header`,
`board-groups`, `bid-board-search` debounce, `review-flags-panel`,
`use-pipeline-job`, `api-layer`).

**Playwright** — 12 specs, chromium, `workers: 1`, `fullyParallel: false`.
`auth`, `bid-lifecycle`, `catalog`, `job-cancel`, `not-found`, `project-delete`,
`proposal-layout` (a pure layout regression guard — aside cards must not overlap
totals while scrolling), `review-flags`, `review-queue`, `settings`, `theme`,
`vendor-rfq`.

`e2e/helpers.ts` provides `signIn`, `openNewBid` and `submitNewBid`. The last
two exist because an empty board mounts `NewBidDialog` twice and the dialog's
submit button shares its accessible name with the trigger, so an unscoped
`/create bid request/i` matches up to three buttons. That only fails against a
freshly bootstrapped database, which is why it was not caught earlier.

> `eslint.config.mjs` ignores `e2e/**`, so the Playwright specs are unlinted.

## Build

- `next.config.ts` — 13 lines: `output: "standalone"` and
  `experimental.proxyClientMaxBodySize: "200mb"`, matching the API's upload cap.
- **Tailwind v4, no config file at all.** `postcss.config.mjs` loads
  `@tailwindcss/postcss`; everything is `@theme` and `@custom-variant` inside
  `app/globals.css`. See [`design-system.md`](design-system.md).
- `tsconfig.json` — strict, bundler resolution, one alias `@/*`.
- `Dockerfile` — three stages on `node:22-bookworm-slim`. The builder sets
  `APP_ENV=production` explicitly so `dev-auth` cannot bake seed credentials at
  build time; `force-dynamic` on `/signin` is the second guard on the same risk.

## Dead weight

Worth knowing before adding to it: `components/shell/stage-panel.tsx` has no
importers, and 13 of the 22 files in `components/ui/` are unused (`badge`,
`checkbox`, `dropdown-menu`, `label`, `progress`, `scroll-area`, `select`,
`separator`, `sheet`, `sonner`, `table`, `tabs`, `tooltip`). The shadcn install
is largely ornamental — the design system in practice is `status-badge.tsx`,
`fetch-error.tsx` and Tailwind utilities over the `@theme` variables.
`components.json` also declares `iconLibrary: "lucide"` while essentially every
component imports Phosphor.
