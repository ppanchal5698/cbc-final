"""pricing's public surface - the only part of pricing another module may import.

- `reference_store` - the referenceData documents, their revisions and seeding.
- `reference_library` - each family read, validated and written.
- `reference_calc` - live margin bands and tax rates.
- `confidence.CONFIDENCE_FLOOR` - NFR-2's 0.75: below it a match is flagged, never
  auto-accepted. The only place the number is written.
- `calc` - the quote arithmetic and the live lookups under one name, for the MCP servers.
- `pricing` - price a line, a margin band for a division, quote totals.
"""
