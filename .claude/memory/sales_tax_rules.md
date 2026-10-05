# Sales Tax and Commercial Basis

## Every quote is supply-only
CBC quotes **material only** — never installation labor, never turnkey.
Standard commercial terms: **HP PO required**, **30-day validity**.

## Sales tax — two states only
Tax is charged **only** where CBC has nexus: **Ohio**, and **Kentucky** (border nexus).
The other 48 states and Canada carry **none**.

The rates are served by `get_tax_rates` and edited in the app at `/settings` (seed:
`data/reference-library/tax/sales_tax_rates.json`, which is not in a run's workspace);
`compute_totals` applies the one for the ship-to state. Do not copy the numbers here -
a copied rate is wrong the day the setting changes.

The sale is to a **GC / corporation**, not to the end customer — which is why the other
48 states carry no tax.

Apply tax from the **ship-to / project location**, not the GC billing address.
If the project state cannot be determined, leave tax **unresolved and flagged** rather than
defaulting to zero.

## Freight
Freight is **generally NOT quoted at estimate stage** — it is handled when a quote becomes
a job. Carry a TBD freight line on the quotation, unpriced.
Exception: Rick occasionally includes freight one-off for customers who demand an
all-inclusive bottom line.

Hager freight reference (account id in `data/reference-library/multipliers/vendor_tiers.json`): prepaid freight at **$1,500** ($5,000 drop-ship);
crating $50.00; itemization/tagging $175.00.

See [project_context](project_context.md), and
[delivery-agent](../agents/delivery-agent.md) for the Phase 6 terms check.
