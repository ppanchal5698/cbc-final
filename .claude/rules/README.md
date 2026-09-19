# Rules and guides

**Everything in `.claude/rules/` is injected into every session.** That is why
only two files are here. A rule in this directory is paid for on every task,
including the ones it has nothing to do with.

| Always loaded | Covers |
|---|---|
| [`00-core-constraints.md`](00-core-constraints.md) | What may be written or deleted, and that nothing reaches a customer without an estimator (NFR-1). Hook-enforced. |
| [`auditability.md`](auditability.md) | The provenance every extracted record and every priced line must carry (NFR-3). |

**Phase guides live in `.claude/guides/` and are NOT auto-loaded.** Read the one
for the phase you are in:

| Guide | Read it when |
|---|---|
| `../guides/extraction.md` | take-off, extraction, matching — confidence bands, the 0.75 review floor, verifying against the sheet before presenting |
| `../guides/pricing.md` | cost sourcing and margin — P21 is read-only, margin bands flag below band |
| `../guides/takeoff.md` | scoping — what CBC quotes and what it deliberately does not |

## Where does a new instruction go?

- **True for every task, and harm if broken** → `rules/`, plus a hook if it can
  be mechanically enforced. A rule nobody enforces is a suggestion.
- **One phase only** → `guides/`, and add a row above.
- **Reference data, not an instruction** → `.claude/memory/`. Never `@`-inline
  it from a rule; that drags it into every session and defeats the point.
- **Reports project status rather than steering behaviour** → `docs/`.

State a constant **once** and point at its owner from elsewhere. A duplicated
threshold is a threshold that will disagree with itself.

Open items and known defects: `docs/data_stewardship.md`.
