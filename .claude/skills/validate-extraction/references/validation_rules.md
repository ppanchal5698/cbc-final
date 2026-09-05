# Validation Rules

## Severity levels

| Level | Meaning | Pipeline behaviour |
|---|---|---|
| **error** | The line cannot be quoted at all | Do not create a line item; report loudly |
| **high** | Quotable but likely wrong without a human | Flag red in the review interface |
| **medium** | Worth a look before sending | Flag yellow |
| **low** | Informational | Note only |

## Field rules

| Check | Severity | Rule |
|---|---|---|
| door_number present | error | The grouping key for the entire quote |
| size resolvable | error | Either 4-digit shorthand or explicit feet-inches |
| source_page present | error | NFR-3 - an unauditable line is not a line |
| fire_rating present on a rated bid | **high** | An unrated match on a rated opening is a defect |
| handing present | high | Handed hardware cannot be matched without it |
| finish present | medium | Usually stated per hardware item, not per door |
| hardware_set callout present | high | Without it there is nothing to match |
| wall_type resolvable | medium | Needed to derive frame depth |
| confidence present, 0.0-1.0 | error | NFR-2 - every match carries a score |
| confidence below 0.75 | high | Flag for review, never auto-accept |
| cost_source recorded | error | One of P21_LAST_PO, LIST_X_MULTIPLIER, VENDOR_RFQ, DISTRIBUTOR_MANUAL, MANUAL |
| margin within band | medium | Below-band flags only; approval routing is deferred |
| out-of-scope item quoted | error | Record it, never price it |

## Anti-inference rule

The most dangerous failure mode is a plausible guess. Specifically forbidden:

- Copying a fire rating from a neighbouring opening
- Defaulting handing to LH because most doors are LH
- Assuming US26D because it is the common finish
- Choosing the nearest stock item to avoid an empty cell
- Extrapolating a price from a similar SKU
- Defaulting sales tax to zero when the project state is unknown

Each of these produces a quote that looks finished and is wrong. A visible gap is
strictly better.

## Reconciliation checks

1. **Opening count** - openings extracted vs door numbers tagged on the floor
   plans. A mismatch usually means a schedule block was missed entirely.
2. **Hardware group coverage** - every `GROUP n` referenced by an opening must
   exist in the HARDWARE GROUPS block, and vice versa.
3. **Page coverage** - list the pages that were read. If a page carrying a
   schedule marker was never parsed, report it.

## Known-pending items that are NOT validation failures

These are flagged but expected, and must not be treated as extraction bugs:

- **Fire rating rules** - Matrix 7.3 / Open Item 9 still unanswered.
- **FRP conversion constants** - Open Item 5 still unanswered.
- **Alternates and addenda handling** - Matrix 4.1 / Open Item 11 still unanswered.
- **Top-10 stock list** - NR-6, CBC still owes the authoritative list.
