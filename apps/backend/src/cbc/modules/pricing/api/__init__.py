"""pricing's public surface - the only part of pricing another module may import.

- `reference_store` - the referenceData documents, their revisions and seeding.
- `reference_library` - each family read, validated and written.
- `reference_calc` - live margin bands and tax rates (re-exported by cbc.core.calc).
- `pricing` - price a line, a margin band for a division, quote totals.
"""
