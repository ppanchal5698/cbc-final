# Margin Governance (NFR-8 / Matrix 6.7) — **DEFERRED**

A margin floor per product type exists so that below-band pricing is visible.
**Approval routing is explicitly out of scope for this phase.**

## Current state (confirmed 14 Jul)
There is **no margin deviation today** — estimators hold to the standard bands.
Approval authority and discount thresholds become relevant only with more estimators.

## What the copilot does now
- Applies the product-type band from @.claude/memory/margin_sheet.md as an **editable default**.
- Records the applied margin and whether it was overridden, plus the override reason.
- **Flags** any line whose margin falls below its band floor (FR-15) into
  review/review_flags.json at severity "medium".
- Does **not** block, route, escalate, or require sign-off.

## Legitimate override reasons (not defects)
- Sourcing changed — bought via a distributor (Banner, SecLock) at higher cost.
- A special-customer margin applies, e.g. Wendy's.
- Lead time or a custom first-build warrants a hand-entered margin.

Record the reason. A below-band margin with **no recorded reason** is what the flag is for.

## Owner
Future phase — President / Sales Management.
