# Pricing

Applies during cost sourcing, pricing and margin application. Not needed during
intake, extraction or take-off.

Merged from `p21-read-only.md` and `margin-governance.md`.

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

Cost older than **6 months** is unreliable; **3 years** or older must be
discarded (Matrix 6.2).

> This is a **different window** from the ~24-month price-sheet review window
> used for vendor sheets. Moving one must not move the other. Both are
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

- Applies the product-type band from `.claude/memory/margin_sheet.md` as an
  **editable default**.
- Records the applied margin, whether it was overridden, and the override reason.
- **Flags** any line whose margin falls below its band floor (FR-15) into
  `review/review_flags.json` at severity `medium`.
- Does **not** block, route, escalate or require sign-off.

> The bands are also served live by `mcp__reference__get_margin_bands` and are
> editable in the app at `/settings`. Where the two disagree, the server is
> newer. Which copy should be authoritative is an open question - see
> `docs/data_stewardship.md`.

### Legitimate override reasons (not defects)

- Sourcing changed — bought via a distributor (Banner, SecLock) at higher cost.
- A special-customer margin applies, e.g. Wendy's.
- Lead time or a custom first-build warrants a hand-entered margin.

Record the reason. A below-band margin with **no recorded reason** is what the
flag is for.

**Owner:** future phase — President / Sales Management.
