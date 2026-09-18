# Data stewardship (NFR-10) — **STATUS: OPEN**

> Moved here from `.claude/rules/data-stewardship.md` by the agent-config audit.
> It reports a project gap rather than steering agent behaviour, so it was
> costing every session context without changing what any agent does. The
> original is preserved at `_archive/.claude/rules/data-stewardship.md`.

Each pricing source needs a **named owner and a refresh cadence** so automated
quotes never run on stale data. **Neither has been assigned yet** (Open Item 15)
— this note records the gap rather than papering over it.

## Sources that need an owner and a cadence

| Source | Path | Owner | Cadence |
|---|---|---|---|
| Reference library | `reference-library/` | **UNASSIGNED** | **UNDEFINED** |
| Vendor multiplier sheets | `pricebooks/` | **UNASSIGNED** | **UNDEFINED** |
| Margin sheet | `reference-library/margins/` | **UNASSIGNED** | **UNDEFINED** |
| Top-10 stock list | `reference-library/hardware_sets/` | **UNASSIGNED** (CBC to provide, NR-6) | **UNDEFINED** |

## What the Ops-Hub changed

Staleness is now **visible to the person who can act on it**, not just to a log:

- The price-books screen shows every program with its age, and flags anything
  past ~24 months or carrying no effective date at all.
- The rail badge carries the stale count on every screen.
- `catalog.list_price_books` returns `ageDays` and `stale`, so a pricing pass
  sees the same signal the estimator does.
- Purchasing can record a review date and upload a newer sheet in one place, and
  a new sheet now records the one it superseded.
- A proposal whose lines are priced off a lapsed sheet **cannot be handed off**
  until purchasing confirms the cost or a named person overrides it, with that
  name written to `auditLogs`.

**None of this assigns an owner or a cadence.** The gap is unchanged; it is
merely harder to miss, and now has one hard gate behind it. NFR-10 stays OPEN
until CBC names a person and an interval.

## Interim mitigation

- Every price-book file carries its **effective date** in `pricebooks/index.json`
  and that date is echoed onto every priced line (see
  `.claude/rules/auditability.md`).
- `scripts/refresh_pricebooks.sh` reports the age of each price book and warns
  past **~24 months**.
- Manually entered prices always show the **"price may be out of date — refresh"**
  prompt (NR-2).
- The P21 freshness rule (more than 6 months unreliable, more than 3 years
  discard — Matrix 6.2) applies independently. It is a **different window** from
  the ~24-month price-sheet one above, and moving one must not move the other.
  That rule lives in `.claude/guides/pricing.md`.

## Risk if left open

Stale price sheets drive wrong quotes — silently, and at scale.

**Owner:** CBC Purchasing and Estimating. **Still to be named.**
