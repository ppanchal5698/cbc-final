---
name: generate-quotation
description: >
  Renders the draft quotation - grouped by door with subtotals, a separate
  restroom-accessories block, an FRP block, a TBD freight line, and standard
  commercial terms. Produces projects/{project}/quotation.html from the priced
  line items. Use in Phase 4/6 of a CBC bid, after every line has a cost and a
  margin.
---

# Generate Quotation

## Structure the estimator expects

1. **Header** - Hamilton Parker Company / CBC, quote number, date, 30-day validity
2. **Customer block** - GC name, initiator, project name, location, bid due date
3. **Doors, grouped by door** - one block per opening: frame, door, then each
   hardware item, with a **subtotal per door**
4. **Restroom accessories** - a separate block, never mixed into the door groups
   (partitions, grab bars, mirrors, dispensers, hand dryers)
5. **FRP** - its own block when in scope (panels, trim, adhesive)
6. **Freight** - a `TBD` line, unpriced. Freight is handled when a quote becomes a
   job, not at estimate stage
7. **Grand total**, with sales tax only for Ohio and Kentucky
8. **Commercial terms** - HP PO required, supply-only material, 30-day validity
9. **Footer** - estimator name and contact

## Where you stop

Run `python scripts/validate_and_render_quote.py <project>` to produce
`quotation.html`. **If validation exits non-zero, stop** — report errors to
pricing-engineer; never patch `priced/line_items.json` with ad-hoc scripts.

After a successful render, version via `mcp__artifact-storage__save_artifact`
(Read the file from disk first). **Stop.** Do not emit "Draft ready for
estimator review" — delivery-agent owns that message.

## Lines that are not fully priced

Never hide them. Render them in place with:

- `PRICE PENDING - MANUAL` for manual cut-off items
- `AWAITING VENDOR QUOTE` for RFQ lines
- `price may be out of date - refresh` for distributor-bought lines

A quote with three visible gaps is useful. A quote with three silently guessed
numbers is dangerous.

## Reference data

- @.claude/memory/sales_tax_rules.md
- @.claude/memory/process_flow.md - Phase 6

## Script

```bash
python .claude/skills/generate-quotation/scripts/render_quote.py dutch_bros_macarthur_2026
```

## Output

`projects/{project}/quotation.html`. Phase 6 delivery-agent emits
**"Draft ready for estimator review"** after final deliverables exist.
