---
description: Match products and price lines
---

Follow the product-matcher agent in `.claude/agents/product-matcher.md`, then
the pricing-engineer agent in `.claude/agents/pricing-engineer.md`.

Match extracted openings to the catalog/reference library, source costs via
P21 / list x multiplier / RFQ, apply margin bands, and save priced lines via
`save_artifact`. Do not send the quote.
