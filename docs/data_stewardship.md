# Open items

Things the system does not do, or does not yet have an owner for. Recorded here
rather than in a rule, because they report status rather than steering
behaviour.

---

## NFR-10 — Data stewardship: **OPEN**

Every pricing source needs a **named owner and a refresh cadence** so automated
quotes never run on stale data. Neither has been assigned.

| Source | Path | Owner | Cadence |
|---|---|---|---|
| Reference library | `data/reference-library/` | **unassigned** | **undefined** |
| Vendor multiplier sheets | `data/pricebooks/` | **unassigned** | **undefined** |
| Margin sheet | `data/reference-library/margins/` | **unassigned** | **undefined** |
| Top-10 stock list | `data/reference-library/hardware_sets/` | **unassigned** (CBC to provide, NR-6) | **undefined** |

### What exists instead

Staleness is **visible to the person who can act on it**, which is not the same
as owned:

- The price-books screen shows every program with its age and flags anything
  past ~24 months or carrying no effective date at all.
- The rail badge carries the stale count on every screen.
- `catalog.list_price_books` returns `ageDays` and `stale`, so a pricing pass
  sees the same signal the estimator does.
- Purchasing can record a review date and upload a newer sheet in one place.
- Every price-book file carries its effective date in `data/pricebooks/index.json`,
  and that date is echoed onto every priced line as `price_book_version`.
- A manually entered price always shows the "price may be out of date — refresh"
  prompt (NR-2).

**None of that assigns an owner or an interval.** The gap is unchanged; it is
merely harder to miss.

### Three freshness windows, deliberately independent

Do not collapse these — they answer different questions, and moving one must not
move the others:

| Window | Applies to | Where |
|---|---|---|
| ~6 months | a P21 purchase-order price is reliable | `ops/api/freshness_rules.classify` |
| 3 years | a P21 price is discarded outright | same |
| ~24 months | a vendor price sheet is flagged stale | the price-books screen |
| per-quote | a priced line has lapsed and blocks the proposal | `quoting/domain/freshness.is_lapsed` |

**Risk if left open:** stale price sheets drive wrong quotes — silently, and at
scale.

**Owner:** CBC Purchasing and Estimating. Still to be named.

---

## NFR-8 — Margin approval routing: **deferred**

A margin floor per product type exists so below-band pricing is visible.
**Approval routing is explicitly out of scope for this phase.**

There is no margin deviation today — estimators hold to the standard bands.
Approval authority and discount thresholds become relevant with more estimators.

What the copilot does now: applies the product-type band as an **editable
default**, records the applied margin and any override reason, and **flags** a
line below its band floor (FR-15) into `review/review_flags.json` at severity
medium. It does not block, route, escalate or require sign-off.

Legitimate override reasons, which are not defects: sourcing changed (bought
through a distributor at higher cost), a special-customer margin applies, or
lead time and a custom first build warrant a hand-entered number. A below-band
margin with **no recorded reason** is what the flag is for.

**Owner:** future phase — President / Sales Management.

---

## NR-10 — P21 integration: **under investigation**

Access is **read-only**, initially and otherwise. There is no write-back, and
`p21-connector` exposes no write tools by design.

Known risks that keep manual entry a first-class path rather than a fallback:

- **P21 item IDs frequently differ from manufacturer part numbers.**
- **Semi-custom items will not match at all.**
- The **supplier list** and **supplier cost** fields are not reliably maintained
  by purchasing. The last-PO price is the truth.

When P21 is unreachable — the normal case today — the connector returns a
structured "manual entry required" response. It never returns a guessed price.

**Owner:** CBC IT. Integration feasibility still under investigation.

---

## FRP conversion constants: **pending**

`data/reference-library/frp_constants/conversion_constants.json` is marked
`PENDING`. Until an estimator supplies the linear-feet-to-panel and
corner-to-trim conversions, [Phase 3b](pipeline/phase-3b-frp.md) records the
measured geometry and leaves material quantities **null and flagged**.

A measured perimeter with no panel count is an honest artifact. A panel count
from a guessed constant is a wrong number that looks right.

---

## Known defects

Found during the September 2026 documentation pass. Recorded rather than fixed,
because each is separate work.

| What | Where |
|---|---|
| `run_full_pipeline.sh` calls a `scripts/validate_project.py` that does not exist, so its pre-flight gate exits 1 before anything runs | `workflows/run_full_pipeline.sh:28` |
| `scripts/init_project.sh` is named as the way to create a project and does not exist | `workflows/_phase.sh:44`, `workflows/run_full_pipeline.sh:18` |
| An always-loaded rule cites a missing `scripts/export_audit_report.py` | `.claude/rules/auditability.md:30` |
| `MONGODB_READONLY_URI` is in neither compose nor `.env.example`, yet three MCP servers refuse to start without it — it works only because the worker derives it at runtime | `infra/docker-compose.yml`, `.env.example` |
| `permissions.allow` ends with `"*"`, making every preceding entry decorative; only `deny` and the hooks bite | `.claude/settings.json` |
| `_check_inline_python` resolves only **literal** paths, so a write through a variable (`p = Path(rel); p.write_text(...)`) reaches a protected directory that the same write as a `Write` tool call would be blocked from | `.claude/hooks/pre_delete_guard.py` |
| The workflow tells `delivery-agent` to export the PDF; the agent definition says not to, and the agent definition won | `workflows/phase6_deliver.sh` |
| "Five stdio MCP servers" — there are eight, and the table omits two | `mcp-servers/README.md` |
| `components/shell/stage-panel.tsx` has no importers; 13 of 22 `components/ui/*` are unused | `apps/web` |
| Board status is derived in three places that can disagree | `lib/board.ts`, `components/bids/board-groups.tsx:40`, `app/(app)/dashboard/page.tsx:39` |
| `intake` imports `quoting`, putting it at the top of the dependency graph; the edge may be vestigial via a retired job type | `intake/features/RunFullPipeline.py:16` |
| ~40 leftover `e2e_*` fixture projects from CI runs | `data/projects/` |
