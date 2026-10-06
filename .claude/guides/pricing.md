# Pricing

Applies during cost sourcing, pricing and margin application. Not needed during
intake, extraction or take-off.

---

## The cost ladder

`apps/backend/src/cbc/modules/pricing/api/preprice.py` prices every line it can
in code before the pricing pass runs, in this order, stopping at the first rung
that gives a cost:

0. **Allegion check** — Von Duprin, LCN, Schlage and Ives are bought through a
   distributor. The line is `DISTRIBUTOR_MANUAL` with a null cost and no other
   rung is tried.
1. **P21 last PO** (`P21_LAST_PO`). Skipped, with no network call, when P21 is
   not configured.
2. **Special net** (`SPECIAL_NET`) — Hager's special-net sheet.
3. **Product catalog baseline** (`CATALOG_BASELINE`) — a curated
   `catalogItems` row.
4. **List × multiplier** (`LIST_X_MULTIPLIER`).
5. **`MANUAL`**, with a reason naming the rung the line is owed.

A rung whose price sheet has lapsed is skipped with a note, and the next rung is
tried. The pricing pass handles what the ladder leaves: the `MANUAL` and
`DISTRIBUTOR_MANUAL` lines, RFQs and substitutions.

---

## P21 is READ-ONLY (NFR-5)

**P21 access in this workstream is read-only. There is no write-back, initially
or otherwise.**

### Permitted

- Reading the **last purchase-order price** from purchase history or the cost screen.
- Reading the PO date to apply the freshness rule.
- Searching for an item by description or part number.

### Forbidden

- Any create, update or delete against P21.
- Any tool named write / update / insert / post / create on the `p21-connector`
  server — the server exposes **no such tools**, by design.
- Trusting the **supplier list** or **supplier cost** fields. Purchasing does not
  reliably update them; the last-PO price is the truth.

### Known integration risks

- **P21 item IDs frequently differ from manufacturer part numbers.**
- **Semi-custom items will not match at all.**
- Therefore **manual cost entry must always be available** as a first-class path,
  not a fallback bolted on afterwards.
- When P21 is unreachable (the normal case today), the connector returns a
  structured "manual entry required" response — it never returns a guessed price.

### Freshness

A P21 cost has a fresh band and a discard band (Matrix 6.2). The windows are
owned by `apps/backend/src/cbc/modules/ops/api/freshness_rules.py` and editable
in the app's Freshness settings; `mcp__p21-connector__check_freshness` applies
the live values.

> This is a **different window** from the price-sheet review window used for
> vendor sheets (Matrix 6.3). Moving one must not move the other. Both are
> deliberate; they measure different things.

**Owner:** CBC IT and Dash. Integration feasibility is still under investigation
(NR-10).

---

## Margin governance (NFR-8 / Matrix 6.7) — **DEFERRED**

A margin floor per product type exists so that below-band pricing is visible.
**Approval routing is explicitly out of scope for this phase.**

### Current state (confirmed 14 Jul)

There is **no margin deviation today** — estimators hold to the standard bands.
Approval authority and discount thresholds become relevant only with more
estimators.

### What the copilot does now

- Applies the product-type band from `mcp__reference__get_margin_bands` as an
  **editable default**. The bands are edited in the app at `/settings`; the seed
  is `data/reference-library/margins/margin_framework.json`.
- Records the applied margin, whether it was overridden, and the override reason.
- **Flags** any line whose margin falls below its band floor (FR-15) into
  `review/review_flags.json` at severity `medium`.
- A below-band margin with **no recorded reason** blocks proposal approval until
  the estimator enters one. With a reason it is advisory.
- A line with no cost (`MANUAL`, `VENDOR_RFQ`, `DISTRIBUTOR_MANUAL`) also blocks
  approval until it is priced.
- Does **not** route, escalate or require sign-off.

### Legitimate override reasons (not defects)

- Sourcing changed — bought via a distributor (Banner, SecLock) at higher cost.
- A special-customer margin applies, e.g. Wendy's.
- Lead time or a custom first-build warrants a hand-entered margin.

Record the reason. A below-band margin with **no recorded reason** is what the
flag is for.

**Owner:** future phase — President / Sales Management.
