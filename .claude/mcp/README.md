# MCP servers

Eight servers, all local Python processes under [`mcp-servers/`](../../mcp-servers),
configured in [`.mcp.json`](../../.mcp.json). This file is the plain-language
answer to "which one do I reach for"; `.mcp.json` stays the source of truth for
how they start.

**Only one of them writes anything.**

| Server | What it is for | Writes? |
|---|---|---|
| **bid-docs** | The bid set as parsed documents — list documents, get an outline, search or fetch text blocks by page. The structured view of what the GC sent. | no |
| **pdf-tools** | The same PDFs as raw pages — `search_pdf`, `find_sheets`, `extract_tables`, `extract_text`, `get_page_image`, `get_page_size`. Reach for this when you need to *look at the sheet*, which the extraction guide requires before flagging a field missing. | no |
| **catalog** | The parts CBC can quote, and the price books they come from — lookup and search catalog items, find the page a part sits on, get a multiplier or special net, check stock. | no — read-only by design, asserted at import |
| **catalog-docs** | The price books as parsed documents, page by page. The `bid-docs` equivalent for vendor sheets. | no |
| **reference** | Pricing policy, served live: margin bands, tax rates, finish crosswalk, frame depths, vendor tiers, manual adders, FRP constants, lite-kit rates. | no |
| **calc-engine** | The one implementation of the arithmetic — `calculate_line`, `apply_margin`, `compute_totals`, `validate_margin`, `cost_from_list`. Never re-derive a total by hand when this can do it. | no |
| **p21-connector** | Prophet 21 cost history — last-PO price, freshness check, item search. | **no, and it exposes no write tools at all.** See [`../guides/pricing.md`](../guides/pricing.md) |
| **artifact-storage** | Saving an estimator-facing artifact with schema validation and SHA-256 versions — `save_artifact`, `get_artifact`, `list_versions`, `propose_patch`. | **yes — the only writer.** Confined to `CBC_PROJECTS_ROOT` |

## Two things worth knowing

**`reference` returns live data; `.claude/memory/` restates some of it.** Margin
bands, the finish crosswalk, frame depths, vendor tiers and tax rates are all
editable in the app at `/settings` and served here. The matching memory files
are copies that nothing keeps in step. Where they disagree, this server is
newer. See `AUDIT_FINDINGS.md` §5.1 — which should be authoritative is an open
question.

**Checkpoint artifacts must go through `artifact-storage`.** A bare `Write` to
`extracted/` or `priced/line_items.json` is blocked by PreToolUse, rule
`checkpoint-save-artifact`. That is deliberate: those files need schema
validation and version history. See
[`../rules/00-core-constraints.md`](../rules/00-core-constraints.md).

## Permissions

The interactive allow-list is in [`../settings.json`](../settings.json).
Workers skip permission prompts; PreToolUse hooks still fire either way.
