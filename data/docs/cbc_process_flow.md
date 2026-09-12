# CBC Estimating Process - Phase 0 to 6

Current-state process, confirmed with Kevin, Rick and Shanna on 14 Jul 2026.

> **Reading the specs and drawings up front is the single largest time cost in
> every bid.** That is the problem this system exists to attack.

| Phase | Activity | System / tool today | Output | Copilot agent |
|---|---|---|---|---|
| **0 - Intake** | Receive bid request | Outlook (mostly email; sometimes phone) | Bid set PDFs, alternates and due date noted | `intake-coordinator` |
| **1 - File setup** | Create job workbook | Excel (password `estimator`) | New job workbook | `intake-coordinator` |
| **2 - Spec scoping** | Identify Div 08 and Div 10 scope | PDF specs | Confirmed scope, rating and HW notes | `spec-scope-analyst` |
| **3 - Take-offs** | Counts, sizes, handing, rating | Edge viewer / Vu360 | Quantities and opening attributes | `takeoff-engineer` |
| **3b - FRP** | Wall-panel measurement | Vu360 + calculator | FRP material quantities | `frp-specialist` |
| **4 - Pricing and build** | Populate and price the quote | Excel + P21 + vendor sheets / RFQ | Priced draft quote | `product-matcher`, `pricing-engineer`, `quote-builder` |
| **4b - Alternates and addenda** | Base bid plus alternates; reconcile addenda | Excel / Outlook | Base plus alternates | **PENDING** |
| **5 - Judgment, reuse, RFIs** | Reuse prior jobs, direct equals, RFIs | Excel / email | Resolved quote plus RFIs | `quality-reviewer` |
| **6 - Deliver** | Export and send the proposal | Excel to PDF / Outlook | Customer-facing PDF | `delivery-agent` |

## Copilot output paths

| Phase | Path |
|---|---|
| 0 | `extracted/scope_metadata.json` |
| 2 | `extracted/scope_summary.json` |
| 3 | `extracted/door_schedule.json` |
| 3b | `extracted/frp_takeoff.json` |
| 4 | `priced/line_items.json`, `priced/margin_applied.json`, `quotation.html` |
| 5 | `review/review_flags.json`, `review/review_summary.html` |
| 6 | Halt: **"Draft ready for estimator review"** (nothing is sent) |

Phase 4 margins: `reference-library/margins/margin_framework.json`.

Narrative (not inlined): `docs/cbc_process_flow_narrative.md`
