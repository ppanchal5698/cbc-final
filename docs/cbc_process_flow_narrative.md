# CBC Estimating Process — current-state narrative

Confirmed with Kevin, Rick and Shanna on 14 Jul 2026. The Phase 0–6 table and
Copilot output paths that a run follows live in `docs/cbc_process_flow.md`
(inlined into every session). This file is the longer briefing; reference it by
path when a question needs it.

> **Reading the specs and drawings up front is the single largest time cost in
> every bid.** That is the problem this system exists to attack.

## Phase 0 - Intake

Bids arrive **mostly by email**, with the job workbook plus plans/RFP attached.
Sometimes by phone, which is why a "create new bid request" path exists (NR-5).

Requests come from the **internal initiator in the sales queue** - Kellan, Matt,
Rebecca or Tina, shown far right in the queue view - **not** from the architect.
CBC sells to the GC or internal initiator, never to the end customer.

Note the **bid alternates** and the **bid-due date** at intake.

A bid set may be **one combined PDF or several separate PDFs**. Both must work.

**Copilot output:** `extracted/scope_metadata.json`

## Phase 1 - File setup

Two modes, both of which stay:

- **Templated** (Shanna) - copy an existing job workbook, save-as, and modify per
  the RFP. Clearing the previous job's residual rows is the first task.
- **One-off** (Kevin) - build from scratch. Exceptions: McDonald's and Cava, which
  Kevin works templated.
- Rick works from **his own Excel**.

Workbooks are password-protected: `estimator`.

## Phase 2 - Spec scoping

Scope is identified manually from the spec and RFP PDFs: **Division 08**
doors, frames and hardware, plus **Division 10** specialties, plus **FRP**.

Read the fire ratings and the hardware-set (HW) schedule to confirm exactly what
is being quoted.

Architects specify hardware **by part number and series** - Hager 3400 is grade 1,
3500 is grade 2. Quote that part number, reconciled to CBC's stock list; anything
beyond it goes to the custom/other tab.

Fire-rating capture is **still to confirm** (Matrix 7.3).

**Copilot output:** `extracted/scope_summary.json`

## Phase 3 - Drawing review and take-offs

Drawings are reviewed and taken off manually today in the Edge viewer or Vu360.

Extract per opening: door number, size, handing, finish, fire rating, hardware-set
callout, frame type and wall type (which derives the frame depth).

**Copilot output:** `extracted/door_schedule.json`

## Phase 3b - FRP take-off

Where FRP is specified, Shanna sets the drawing scale in Vu360 and captures
perimeter (LF), inside corners and outside corners.

**Vu360 gives geometry only.** The estimator converts to material quantities by
hand on a calculator and types them in. The **conversion constants are still to be
provided** (Open Item 5) - so the copilot captures geometry and stops.

**Copilot output:** `extracted/frp_takeoff.json`

## Phase 4 - Pricing and build

The workbook is a calculator. Only **three** cells are human per line:
**Quantity**, **Our Cost**, **Margin**. Everything to the right computes.

```
Sale $ EA = Cost / (1 - margin)
Unit      = Sale $ EA
Ext       = Unit x Qty
Sub-total = Sale $ EA x Qty
Grand tot = SUM(sub-totals)
```

The legacy **unit weight** column is gone - it dated from truck-loading years ago.

Three cost paths (see `docs/requirements_matrix.md` 6.2, 6.3, 6.6):

1. **P21 last-PO price** - not the supplier-list or supplier-cost fields
2. **List price x multiplier** - per-vendor tier
3. **Distributor lookup or vendor RFQ** - manual entry

Margin bands live in `reference-library/margins/margin_framework.json`. Overridable
per quote by sourcing.

Freight is usually carried **TBD**.

**Copilot output:** `priced/line_items.json`, `priced/margin_applied.json`,
`quotation.html`

## Phase 4b - Alternates and addenda - **PENDING**

Commercial bids commonly carry bid alternates and are revised mid-bid by addenda
that change scope, products or counts.

**Formal handling was not covered in the 14 Jul session** (Matrix 4.1, FR-14,
Open Item 11). Interim behaviour: keep the base bid and each alternate as
**distinct, comparable line groups**, and never overwrite prior work when an
addendum lands.

## Phase 5 - Judgment, reuse and RFIs

- **Reuse** the closest prior quote for a repeat brand, architect or GC (FR-11).
- **Value-engineering / direct equals**: when a specified line is not available,
  propose the closest of the top 2-3 brands **with a note**. The GC approves.
- **Raise RFIs** for unclear or missing information before finalising.

**Copilot output:** `review/review_flags.json`, `review/review_summary.html`

## Phase 6 - Deliver

Export a PDF proposal:

- doors, frames and hardware **grouped by door with subtotals**
- a **separate restroom-accessories block**
- a freight line, usually **TBD**
- standard commercial terms: **HP PO required**, **30-day validity**,
  **supply-only material**
- sales tax for **Ohio (~8%) and Kentucky (6.5%)** only; the other 48 states and
  Canada are untaxed

Send back to **whoever initiated the request in the queue** - not a group email.
That person deals with the customer.

**The copilot stops here.** It writes the draft and reports
**"Draft ready for estimator review"**. A human sends it (NFR-1).
