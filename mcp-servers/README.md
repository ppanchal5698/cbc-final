# CBC MCP Servers

Five stdio MCP servers backing the estimating pipeline.

| Server | Tools | Purpose |
|---|---|---|
| `pdf-tools` | `extract_text`, `extract_tables`, `get_page_image`, `search_pdf` | Read bid-set PDFs; every result carries `source_page` |
| `catalog` | `find_pages`, `get_page`, `get_multiplier`, `get_special_net`, `is_stock_item`, `list_catalogs`, `get_catalog_overview` | Cost path 2: **which page** to open. It returns no prices - the price is read off the sheet with `pdf-tools`. Multiplier/net/stock tools are thin wrappers over the `reference` store |
| `reference` | `list_reference_families`, `get_reference_document`, `get_margin_bands`, `get_tax_rates`, `get_finish_crosswalk`, `get_frame_depth`, `get_frp_constants`, `get_manual_adders`, `get_special_customer_margin`, `get_vendor_tier`, `get_special_net`, `lookup_lite_kit`, `is_stock_item`, `get_custom_other_matrix` | **READ-ONLY** curated pricing knowledge from Mongo `referenceData` (seed JSON under `reference-library/` is fixtures only) |
| `calc-engine` | `cost_from_list`, `lookup_lite_kit_list_price`, `calculate_line`, `apply_margin`, `compute_totals`, `validate_margin` | The only quote arithmetic in the system |
| `artifact-storage` | `save_artifact`, `get_artifact`, `list_versions`, `list_project_files` | Project writes with SHA-256 version history |
| `p21-connector` | `lookup_last_po`, `check_freshness`, `search_item` | Cost path 1, **READ-ONLY** |

## Install

```bash
python -m pip install -r pdf-tools/requirements.txt -r catalog/requirements.txt
```

Or install everything at once from the shared project:

```bash
python -m pip install -e mcp-servers
```

Optional OCR support for scanned bid sets (also needs the `tesseract` binary):

```bash
python -m pip install pytesseract
```

## Verify

```bash
python mcp-servers/main.py --selftest
```

This lists each server's tools and runs the three self-check demos
(`calc-engine`, `artifact-storage`, `p21-connector`).

## Registration

The servers are registered in **`.mcp.json` at the repo root**, not in
`.claude/settings.json` - a `mcpServers` block there is ignored, and a run that
relies on it silently gets no tools.

Which servers a given job actually receives is narrower still: `cbc/core/toolsets.py`
scopes each job type to the servers its phase uses and passes `--strict-mcp-config`,
so the list is exhaustive rather than additive. To add a server to a different
Claude Code project:

```bash
claude mcp add pdf-tools -- python mcp-servers/pdf-tools/server.py
```

```bash
claude mcp add catalog -- python mcp-servers/catalog/server.py
```

```bash
claude mcp add calc-engine -- python mcp-servers/calc-engine/server.py
```

```bash
claude mcp add artifact-storage -- python mcp-servers/artifact-storage/server.py
```

```bash
claude mcp add p21-connector -- python mcp-servers/p21-connector/server.py
```

## Environment

| Variable | Used by | Default |
|---|---|---|
| `PRICEBOOK_DIR` | `catalog` | `pricebooks/` |
| `P21_BASE_URL` | `p21-connector` | unset - every lookup returns "manual entry required" |
| `P21_API_KEY` | `p21-connector` | unset |

Put credentials in `.claude/settings.local.json`, which is gitignored. Never commit them.

## Design notes

- **`_runtime.py`** holds the stdio/protocol wiring shared by all five servers.
  Each `server.py` is domain logic plus a `TOOLS` list and a `HANDLERS` map.
- **`extract_tables` clusters word positions rather than detecting ruled tables.**
  Architectural sheets are CAD exports - one sheet in the Dutch Bros fixture carries
  over 13,000 vector line segments, and ruling-based detection returns mostly noise.
- **Fuzzy matching uses stdlib `difflib`**, not rapidfuzz. The job is mostly exact
  part-number containment; the extra dependency did not earn its place.
- **`p21-connector` exposes no write tools** and asserts this at import time (NFR-5).
