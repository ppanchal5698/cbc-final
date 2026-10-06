# MCP servers

Eight servers, all local Python processes under [`mcp-servers/`](../../mcp-servers),
configured in [`.mcp.json`](../../.mcp.json). This file is the plain-language
answer to "which one do I reach for"; `.mcp.json` stays the source of truth for
how they start.

**Only one of them writes anything.**

| Server | What it is for | Writes? |
|---|---|---|
| **bid-docs** | The bid set as parsed documents — list documents, get an outline, search or fetch text blocks by page. The structured view of what the GC sent. | no |
| **pdf-tools** | The same PDFs as raw pages — `search_pdf`, `find_sheets`, `extract_tables`, `extract_text`, `get_page_image`, `get_page_size`, and `parse_door_openings` (the deterministic door-schedule parse of one page). Reach for this when you need to *look at the sheet*, which the extraction guide requires before flagging a field missing. | no |
| **catalog** | The parts CBC can quote, and the price books they come from — `recall_match` (what an estimator already confirmed), `lookup_catalog_item`, `search_catalog_items`, `list_catalogs`, `get_catalog_overview`, `find_pages`, `get_page`, `get_multiplier`, `get_special_net`, `is_stock_item`. | no — read-only by design, asserted at import |
| **reference** | Pricing policy, served live from `referenceData` — `get_margin_bands`, `get_tax_rates`, `get_finish_crosswalk`, `get_frame_depth`, `get_vendor_tier`, `get_special_net`, `get_special_customer_margin`, `get_manual_adders`, `get_frp_constants`, `lookup_lite_kit`, `is_stock_item`, `get_custom_other_matrix`, plus `list_reference_families` / `get_reference_document` for a whole family. The only way reference data reaches a pipeline run: `data/reference-library/` is seed, and is not in a run's workspace. | no |
| **calc-engine** | The one implementation of the arithmetic — `calculate_line`, `apply_margin`, `compute_totals`, `validate_margin`, `cost_from_list`, `lookup_lite_kit_list_price`. Never re-derive a total by hand when this can do it. | no |
| **p21-connector** | Prophet 21 cost history — last-PO price, freshness check, item search. | **no, and it exposes no write tools at all.** See [`../guides/pricing.md`](../guides/pricing.md) |
| **artifact-storage** | Saving an estimator-facing artifact with schema validation and SHA-256 versions — `save_artifact`, `get_artifact`, `list_versions`, `list_project_files`, `propose_patch`. | **yes — the only writer.** Confined to `CBC_PROJECTS_ROOT` |

## Two things worth knowing

**`reference` returns live data; `.claude/memory/` restates some of it.** Margin
bands, the finish crosswalk, frame depths, vendor tiers and tax rates are all
editable in the app at `/settings` and served here. The matching memory files
are copies that nothing keeps in step. Where they disagree, this server is
newer. Which copy should be authoritative is still an open question.

**Checkpoint artifacts must go through `artifact-storage`.** A bare `Write` to
`extracted/` or `priced/line_items.json` is blocked by PreToolUse, rule
`checkpoint-save-artifact`. That is deliberate: those files need schema
validation and version history. See
[`../rules/00-core-constraints.md`](../rules/00-core-constraints.md).

## Permissions

The interactive allow-list is in [`../settings.json`](../settings.json).
Workers skip permission prompts; PreToolUse hooks still fire either way.
