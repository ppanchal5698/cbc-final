# Reference data (Mongo)

Live pricing configuration (margins, tax, vendor tiers, special nets, lite-kit,
stock lists, finishes, frame depths, FRP constants, etc.) lives in MongoDB
collection **`referenceData`** — one document per family, `_id` = family name,
payload in `data`.

JSON under `reference-library/` is **seed + fixtures only**. On API startup,
`ensure_indexes()` → `ensure_reference_seed()` inserts any missing family from
`REFERENCE_DIR` and never overwrites an existing document (operator edits win).

- Admin CRUD: `/api/reference/*` on the pricing service (Admin Settings UI).
- Agents: read-only **`reference`** MCP (`mcp-servers/reference/`). Do not `Read`
  seed files for live values; do not write reference data from agents.
- Forced re-seed (ops): `python scripts/seed_reference_data.py --force`
