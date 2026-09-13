"""pricing's public surface - the only part of pricing another module may import.

- `reference_store` - the referenceData documents, their revisions and seeding.
- `reference_library` - each family read, validated and written.
- `reference_calc` - live margin bands and tax rates.
- `calc` - the quote arithmetic and the live lookups under one name, for the MCP servers.
- `pricing` - price a line, a margin band for a division, quote totals.
"""
