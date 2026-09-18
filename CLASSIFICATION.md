# Classification — agent configuration surface

Phase 3 of the config audit. Every discrete instruction fragment placed in
exactly one bucket. Analysis only; nothing changed to produce this.

Buckets: **Core** (true for every task) · **Path-scoped** (one phase or
directory) · **Skill** (trigger-invoked capability) · **Command** (user-invoked)
· **MCP** (tied to one server) · **Archive** (no longer steers) ·
**Review** (cannot classify confidently).

---

## Core / always-load

| Fragment | Source | Why |
|---|---|---|
| Never write outside `projects/{current}/`; never write `pricebooks/` or `reference-library/` during a run | `rules/file-safety.md` | Applies to any file operation in any phase. Hook-enforced (`pre_delete_guard.py`). |
| Never delete outside `projects/`; `rm -rf` and `git push` blocked | `rules/file-safety.md` | Same. Fired in this very session when a push was attempted. |
| Checkpoint artifacts must go through `save_artifact`, not bare Write | `rules/file-safety.md` | Applies to every artifact write. |
| No estimate or quotation is ever sent without estimator approval (NFR-1) | `rules/human-in-the-loop.md` | The product's defining constraint. Hook-enforced (`pre_send_quote.py`). |
| Project identity, module map, run command | `CLAUDE.md` | Orientation; needed before anything else. |

**Total: ~55 lines.** Everything else below is conditional.

## Path-scoped / on-demand

| Fragment | Source | Applies during |
|---|---|---|
| Confidence bands, 0.75 review floor, never infer a missing attribute | `rules/accuracy-trust.md` | extraction / matching |
| Unparsed content must be reported, never silently dropped | `rules/accuracy-trust.md` | extraction |
| Open the specific PDF page before flagging a field missing | `rules/pdf-verify-before-present.md` | extraction |
| Every non-empty schedule cell maps to a field or to `notes` | `rules/pdf-verify-before-present.md` | extraction |
| Provenance required on every extracted record (`source_page`, `bbox`, `page_size`) | `rules/auditability.md` | extraction |
| Provenance required on every priced line (`cost_source`, `multiplier_tier`, …) | `rules/auditability.md` | pricing |
| In-scope / out-of-scope product list; how to handle an out-of-scope item | `rules/scope-boundaries.md` | take-off |
| Margin band is an editable default; below-band flags, never blocks | `rules/margin-governance.md` | pricing |
| P21 is read-only; last-PO price is the truth; supplier fields not trusted | `rules/p21-read-only.md` | pricing |

**Total: ~220 lines**, none of which is needed on a task like this one.

## Skill-triggered

All 10 already have frontmatter with a description and trigger. Reviewed for
overlap; none found — each names a distinct phase and artifact.

`extract-door-schedule` · `extract-div10-takeoff` · `frp-takeoff` ·
`scan-product-catalog` · `match-hardware-sets` · `price-line-item` ·
`apply-margin` · `generate-quotation` · `validate-extraction` ·
`reuse-prior-quote`

**No action.** The six `references/*.md` files under them load only when the
parent skill does, which is correct.

## Command

`/intake` · `/takeoff` · `/price` · `/review` — 37 lines total, each a thin
wrapper over an agent. **No action.**

## MCP-server-specific

Eight servers in `.mcp.json`: `bid-docs`, `catalog`, `catalog-docs`,
`pdf-tools`, `reference`, `calc-engine`, `p21-connector`, `artifact-storage`.

Constraints currently scattered into rules rather than documented with the
server they describe:

| Fragment | Currently in | Belongs with |
|---|---|---|
| p21-connector exposes no write tools, by design | `rules/p21-read-only.md` | `mcp/README.md` |
| catalog MCP is read-only and asserts it at import | `rules/file-safety.md` | `mcp/README.md` |
| artifact-storage is the only writer, under `CBC_PROJECTS_ROOT` | `CLAUDE.md` | `mcp/README.md` |

**No `mcp/README.md` exists.** A reader has to infer each server's purpose from
its name and from rules that mention it in passing.

## Deprecated / candidate for archive

| Fragment | Source | Why |
|---|---|---|
| Entire file — NFR-10 stewardship gap, owner/cadence `UNASSIGNED` | `rules/data-stewardship.md` | Reports project status. Contains no instruction an agent can act on. Belongs in `docs/`. |
| `AGENTS.md` (whole file) | byte-identical to `CLAUDE.md` | Replace with a one-line pointer, as `apps/web/CLAUDE.md` already does. |

## Unclear / needs human review

| Fragment | Source | What is unclear |
|---|---|---|
| Margin bands and divisors | `memory/margin_sheet.md` | Duplicates `get_margin_bands`, and is `@`-inlined into every session. Archive or keep as offline fallback? |
| Finish crosswalk | `memory/finish_nomenclature.md` | Duplicates `get_finish_crosswalk`. |
| Wall type → frame depth | `memory/frame_depths.md` | Duplicates `get_frame_depth`. |
| Vendor multiplier tiers | `memory/vendor_tiers.md` | Duplicates `get_vendor_tier`. |
| State sales-tax rates | `memory/sales_tax_rules.md` | Duplicates `get_tax_rates`. |
| 6-line file | `memory/process_flow.md` | Abandoned stub, or deliberate pointer to `docs/cbc_process_flow.md`? |
| Named estimators and their habits | `memory/estimator_profiles.md` | Should an agent behave differently depending on who is running it? |
| Hook session guard is inert | `.claude/hooks/pre_tool_use.py` | Python, not markdown. Flagged, not touched. |

The remaining six memory files — `cost_sourcing_rules`, `door_notation`,
`fire_rating_rules`, `handing_codes`, `manual_cutoff`, `project_context` —
classify cleanly as **path-scoped reference**, loaded on demand. No action.
