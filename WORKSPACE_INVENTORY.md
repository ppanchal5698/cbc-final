# Workspace inventory — agent configuration surface

Generated 2026-09-18T12:29:39Z. Read-only discovery pass (Phase 1 of the config audit).

**Scope:** this repository. Global `~/.claude/skills/` is excluded — it is
almost entirely vendored plugins (`ponytail`, `anthropic-skills`, `graphify`)
that a plugin update overwrites, so it is not this repo's to refactor. Global
`~/.claude/CLAUDE.md` is 3 lines and already minimal.

**Excluded deliberately:** `.claude/hooks/*.py` (Python, not markdown — flagged
for the human, not edited), `node_modules/`, `.venv/`, `graphify-out/`.

## Load behaviour

| Category | Files | Lines | When it enters context |
|---|---:|---:|---|
| Core (`CLAUDE.md`, `AGENTS.md`) | 2 | 102 | every session |
| `.claude/rules/` | 9 | 318 | **every session, unconditionally** |
| `.claude/memory/` | 13 | 431 | 2 every session (pulled in by rules), 11 on demand |
| `.claude/skills/` | 16 | 1,502 | when a skill's trigger matches |
| `.claude/agents/` | 11 | 1,146 | when that subagent is dispatched |
| `.claude/commands/` | 4 | 37 | when the slash command is invoked |
| `apps/web/` core pair | 2 | 10 | when working in that directory |

The always-loaded payload is therefore **CLAUDE.md + AGENTS.md + 9 rules + 2
memory files**, on every task regardless of what the task is.

## Every file

| Path | Lines | Modified | Type | Content |
|---|---:|---|---|---|
| `CLAUDE.md` | 51 | 2026-09-17 | Core agent file | CBC Estimating Copilot (modular monolith) — Live API + workers: [`apps/backend`](apps/backend). Compose service name |
| `AGENTS.md` | 51 | 2026-09-17 | Core agent file | CBC Estimating Copilot (modular monolith) — Live API + workers: [`apps/backend`](apps/backend). Compose service name |
| `apps/web/CLAUDE.md` | 1 | 2026-09-12 | Core agent file | @AGENTS.md |
| `apps/web/AGENTS.md` | 9 | 2026-09-12 | Core agent file | This is NOT the Next.js you know — This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/ |
| `.claude\rules\accuracy-trust.md` | 40 | 2026-09-17 | Rule | Accuracy and Trust (NFR-2) — **Confidence scoring and review flags are visible from day one. Unmatched or low-confidence |
| `.claude\rules\auditability.md` | 37 | 2026-09-13 | Rule | Auditability (NFR-3) — **Every generated line must be traceable to a source drawing page and to a reference-library |
| `.claude\rules\data-stewardship.md` | 41 | 2026-09-12 | Rule | Data Stewardship (NFR-10) — **STATUS: OPEN** — Each pricing source needs a **named owner and a refresh cadence** so automated quotes never |
| `.claude\rules\file-safety.md` | 35 | 2026-09-14 | Rule | File Safety — - Write **only** inside projects/{current_project}/ during a pipeline run. |
| `.claude\rules\human-in-the-loop.md` | 27 | 2026-09-12 | Rule | Human-in-the-Loop (NFR-1) — **No estimate or quotation is ever sent to a customer without explicit estimator approval.** |
| `.claude\rules\margin-governance.md` | 25 | 2026-09-12 | Rule | Margin Governance (NFR-8 / Matrix 6.7) — **DEFERRED** — A margin floor per product type exists so that below-band pricing is visible. |
| `.claude\rules\p21-read-only.md` | 26 | 2026-09-12 | Rule | P21 is READ-ONLY (NFR-5) — **P21 access in this workstream is read-only. There is no write-back, initially or otherwise.** |
| `.claude\rules\pdf-verify-before-present.md` | 51 | 2026-09-17 | Rule | PDF verify before present (NFR-2 / NFR-3) — **If a value is unclear, incomplete, or about to be flagged missing — open the |
| `.claude\rules\scope-boundaries.md` | 36 | 2026-09-12 | Rule | Scope Boundaries — Quote what is in scope. **Do not attempt to price anything on the out-of-scope list** — flag |
| `.claude\memory\cost_sourcing_rules.md` | 56 | 2026-09-17 | Memory | Cost Sourcing Rules — the three paths — Cost is sourced by one of exactly three paths. **Record which path was used, and the date, |
| `.claude\memory\door_notation.md` | 23 | 2026-09-17 | Memory | Door Size Notation — Four-digit shorthand. **First two digits = width, second two = height**, each read as |
| `.claude\memory\estimator_profiles.md` | 29 | 2026-09-17 | Memory | Estimator Profiles — the three working styles — Two estimating modes coexist and **both stay**. Do not force one on the other. |
| `.claude\memory\finish_nomenclature.md` | 36 | 2026-09-12 | Memory | Finish Nomenclature — **Two nomenclature systems are in active use and both must be interpreted** (NR-3). |
| `.claude\memory\fire_rating_rules.md` | 46 | 2026-09-17 | Memory | Fire Rating and Labels — Openings carry fire ratings — commonly **20 / 45 / 60 / 90-minute, UL-labelled**. |
| `.claude\memory\frame_depths.md` | 20 | 2026-09-17 | Memory | Frame Depth by Wall Type — Frame **throat / depth** is derived from the wall construction. Five standard throat sizes |
| `.claude\memory\handing_codes.md` | 33 | 2026-09-17 | Memory | Door Handing and Swing — Hardware selection depends on **handing**. Capture it per opening so handed hardware |
| `.claude\memory\manual_cutoff.md` | 30 | 2026-09-17 | Memory | The Manual Cut-off (NR-13 — design principle) — **Automate the stock / top-N items. Beyond that, stop.** |
| `.claude\memory\margin_sheet.md` | 35 | 2026-09-17 | Memory | Margin Framework — Margin is applied **by product type, as a divisor**. The framework has been stable ~14 years. |
| `.claude\memory\process_flow.md` | 6 | 2026-09-12 | Memory | CBC Process Flow — The canonical Phase 0–6 workflow lives in **`docs/cbc_process_flow.md`**. Read |
| `.claude\memory\project_context.md` | 32 | 2026-09-17 | Memory | Project Context — who CBC is — **CBC** = Construction Building Components, the national-accounts division of |
| `.claude\memory\sales_tax_rules.md` | 33 | 2026-09-17 | Memory | Sales Tax and Commercial Basis — CBC quotes **material only** — never installation labor, never turnkey. |
| `.claude\memory\vendor_tiers.md` | 52 | 2026-09-17 | Memory | Vendor Tiers & Multipliers — Cost for a non-special item = **manufacturer list price x CBC's customer-specific multiplier**. |
| `.claude\skills\apply-margin\SKILL.md` | 80 | 2026-09-12 | Skill | > Applies the CBC product-type margin framework as an editable default per line, computes Sale $ EA = Cost / (1 - margin), and flags any line below its band floor. Handles sourcing-driven ov |
| `.claude\skills\apply-margin\references\margin_bands.md` | 46 | 2026-09-12 | Skill | Margin Bands — Read `reference-library/margins/margin_framework.json` via seed only for humans; |
| `.claude\skills\extract-div10-takeoff\SKILL.md` | 71 | 2026-09-17 | Skill | > Extracts Division 10 specialty take-off lines — toilet partitions, restroom accessories, washroom equipment, and hand dryers — with type, manufacturer, location, and counts. Use in Phase 3 |
| `.claude\skills\extract-door-schedule\SKILL.md` | 189 | 2026-09-17 | Skill | > Extracts the door / opening schedule from an architectural PDF. Captures door number, size (4-digit notation or explicit feet-inches), handing (LH/RH/LHR/RHR), finish (US26D/626 dual nomen |
| `.claude\skills\extract-door-schedule\references\schedule_anatomy.md` | 145 | 2026-09-17 | Skill | Door Schedule Anatomy — Not on the pages that merely *mention* it. Spec pages and drawing indexes say |
| `.claude\skills\frp-takeoff\SKILL.md` | 120 | 2026-09-17 | Skill | > Performs the FRP wall-panel take-off - captures product type, manufacturer, location, drawing/Vu360 scale, perimeter linear feet, inside and outside corner counts, wall height, and panel/t |
| `.claude\skills\frp-takeoff\references\frp_constants.md` | 57 | 2026-09-17 | Skill | FRP Conversion Constants - **PENDING** — **These constants do not exist yet.** Open Item 5: CBC (Shanna / Vu360) still owes |
| `.claude\skills\generate-quotation\SKILL.md` | 63 | 2026-09-12 | Skill | > Renders the draft quotation - grouped by door with subtotals, a separate restroom-accessories block, an FRP block, a TBD freight line, and standard commercial terms. Produces projects/{pro |
| `.claude\skills\match-hardware-sets\SKILL.md` | 101 | 2026-09-12 | Skill | > Matches each extracted opening and hardware-group item to the CBC reference library, respecting fire rating, handing and finish. Assigns a confidence score per match and flags anything bel |
| `.claude\skills\match-hardware-sets\references\hw_set_library.md` | 57 | 2026-09-12 | Skill | Hardware Set Library — Confirmed in the 14 Jul estimator session. Sets are built around the **top-10 |
| `.claude\skills\price-line-item\SKILL.md` | 94 | 2026-09-17 | Skill | > Prices one quote line by choosing between CBC cost paths - P21 last-PO, special net, product catalog (catalogItems) baseline, vendor list x multiplier, or distributor/vendor-RFQ manual ent |
| `.claude\skills\price-line-item\references\cost_paths.md` | 137 | 2026-09-17 | Skill | The Three Cost Paths — **Use when:** the item is regularly bought or carries special pricing in P21. |
| `.claude\skills\reuse-prior-quote\SKILL.md` | 64 | 2026-09-12 | Skill | > Finds the closest prior CBC quote - same brand, architect or GC - and offers it as a starting draft rather than building from scratch. This is the templated estimating mode (FR-11). Use at |
| `.claude\skills\scan-product-catalog\SKILL.md` | 101 | 2026-09-17 | Skill | > Finds which page of which vendor price book carries a part - Hager, National Guard, PEMKO/Markar, Rockwood, ASI, Bobrick, Bradley, Gamco, World Dryer, NUDO - searching by part number, seri |
| `.claude\skills\validate-extraction\SKILL.md` | 112 | 2026-09-17 | Skill | > Validates extracted bid data before it is priced - checks required fields per opening, verifies fire ratings were not silently dropped on rated openings, and reports unparsed content. Use  |
| `.claude\skills\validate-extraction\references\validation_rules.md` | 65 | 2026-09-17 | Skill | Validation Rules — The most dangerous failure mode is a plausible guess. Specifically forbidden: |
| `.claude\agents\delivery-agent.md` | 63 | 2026-09-17 | Agent | > Phase 6 / FR-10 agent. Prepares the email body for routing back to the sales initiator and verifies review artifacts. The worker (not this agent) renders quotation.html → quotation.pdf via |
| `.claude\agents\div10-specialist.md` | 53 | 2026-09-17 | Agent | > Phase 3c agent. When Division 10 specialties are in scope, extracts product type, manufacturer, location/drawing reference, and counts for toilet partitions, restroom accessories, washroom |
| `.claude\agents\frp-specialist.md` | 74 | 2026-09-17 | Agent | > Phase 3b agent. Where FRP wall panels are specified, extracts product type, manufacturer, location, drawing/Vu360 scale, perimeter linear feet, inside and outside corner counts, wall heigh |
| `.claude\agents\intake-coordinator.md` | 133 | 2026-09-14 | Agent | > Phase 0/1 agent. Receives a bid request - an emailed bid set, an RFP, or a phoned-in request - creates the project scaffold under projects/{name}/, moves uploaded PDFs into uploads/raw/, a |
| `.claude\agents\pricebook-ingestor.md` | 83 | 2026-09-12 | Agent | > Reads an uploaded vendor price book or multiplier sheet and writes the parts it finds into the product catalog, each with the page it was read from. Runs when purchasing uploads a new shee |
| `.claude\agents\pricing-engineer.md` | 142 | 2026-09-17 | Agent | > Phase 4 agent. Prices every matched line using CBC cost paths - P21 last-PO, special net, product catalog baseline, list x multiplier, or distributor/RFQ manual entry - applies the product |
| `.claude\agents\product-matcher.md` | 130 | 2026-09-17 | Agent | > FR-4 agent. Matches every extracted opening and hardware item to the closest entry in the CBC reference library, respecting fire rating, handing, finish, series and manufacturer preference |
| `.claude\agents\quality-reviewer.md` | 106 | 2026-09-17 | Agent | > Phase 5 / FR-8 / FR-9 agent. Scores confidence on every match, flags low-confidence items, missing fire ratings, unparsed content and below-band margins, verifies unclear findings against  |
| `.claude\agents\quote-builder.md` | 83 | 2026-09-17 | Agent | > Phase 4/6 agent. Builds the draft quotation - grouped by door with subtotals, a separate restroom-accessories block, an FRP block, a TBD freight line and the grand total - and renders it t |
| `.claude\agents\spec-scope-analyst.md` | 104 | 2026-09-17 | Agent | > Phase 2 agent. Reads the specification PDFs to identify Division 08 (doors, frames, hardware) and Division 10 (specialties, partitions, accessories, washroom equipment) scope, extracts fir |
| `.claude\agents\takeoff-engineer.md` | 175 | 2026-09-17 | Agent | > Phase 3 agent. Checks the deterministic door schedule against the sheets it was read from, fills nulls from sheet evidence only using the FR-2 estimator checklist, verifies every unclear o |
| `.claude\commands\intake.md` | 8 | 2026-09-16 | Command | Run bid intake (phase 0/1) |
| `.claude\commands\price.md` | 10 | 2026-09-16 | Command | Match products and price lines |
| `.claude\commands\review.md` | 9 | 2026-09-16 | Command | Generate the estimator review report |
| `.claude\commands\takeoff.md` | 10 | 2026-09-16 | Command | Extract door, FRP, and Div 10 takeoff |
| `.mcp.json` | 76 | 2026-09-17 | MCP / config | (config, not markdown - not edited by this pass) |
| `.claude/settings.json` | 70 | 2026-09-17 | MCP / config | (config, not markdown - not edited by this pass) |
| `.graphifyignore` | 1 | 2026-09-12 | MCP / config | web/public/pdf.worker.min.mjs |

