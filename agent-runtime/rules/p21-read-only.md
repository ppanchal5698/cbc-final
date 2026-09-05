# P21 is READ-ONLY (NFR-5)

**P21 access in this workstream is read-only. There is no write-back, initially or otherwise.**

## Permitted
- Reading the **last purchase-order price** from purchase history or the cost screen.
- Reading the PO date to apply the freshness rule.
- Searching for an item by description or part number.

## Forbidden
- Any create, update, or delete against P21.
- Any tool named write / update / insert / post / create on the p21-connector server —
  the server exposes **no such tools**, by design.
- Trusting the **supplier list** or **supplier cost** fields. Purchasing does not reliably
  update them; the last-PO price is the truth.

## Known integration risks
- **P21 item IDs frequently differ from manufacturer part numbers.**
- **Semi-custom items will not match at all.**
- Therefore **manual cost entry must always be available** as a first-class path, not a
  fallback bolted on afterwards.
- When P21 is unreachable (the normal case today), the connector returns a structured
  "manual entry required" response — it never returns a guessed price.

## Owner
CBC IT and Dash. Integration feasibility is still under investigation (NR-10).
