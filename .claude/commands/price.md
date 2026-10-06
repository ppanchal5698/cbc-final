---
description: Match products and price lines
---

Follow the product-matcher agent in `.claude/agents/product-matcher.md`, then
the pricing-engineer agent in `.claude/agents/pricing-engineer.md`.

Match extracted openings to the catalog/reference library and save
`extracted/hardware_sets.json` via `save_artifact`. `priced/line_items.json` is
already priced in code (Allegion check → P21 → special net → catalog → list ×
multiplier), so price only the lines it left `MANUAL` or `DISTRIBUTOR_MANUAL`,
with `propose_patch` on pricing fields -
a whole-file `save_artifact` over it is refused. Do not send the quote.
