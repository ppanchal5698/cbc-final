# MCP servers

Eight stdio servers under `mcp-servers/`. They are how a Claude pass reads bid
PDFs, looks up parts and prices, does arithmetic, and writes artifacts. Seven of
them are read-only by construction; `artifact-storage` is the only writer, and
it is confined rather than trusted.

Each server is a directory with `server.py` (domain logic plus `TOOLS` and
`HANDLERS`) and `tools.py` (JSON schemas only). `p21-connector` adds
`client.py`.

## The runtime

`mcp-servers/_runtime.py` is the entire protocol layer.
`serve(name, TOOLS, HANDLERS, demo=...)` builds an MCP SDK 2.x `Server` with
`on_list_tools` / `on_call_tool` callables. Handlers run through
`asyncio.to_thread`; an exception comes back as
`{"error", "tool", "arguments"}` with `is_error=True` — never swallowed, never
turned into an empty result. `dump_payload` serialises compactly, because indent
is tokens.

`load_server(name)` imports one server under a unique module name and pre-loads
its siblings under their bare names. That exists because every server file is
called `server.py` and does `from tools import TOOLS`.

`serve` also handles `--selftest` (asserts every tool has a handler, prints the
tool list) and `--demo`.

`mcp-servers/main.py` is the CI gate. It reads the server list from `.mcp.json`
rather than keeping its own — a hand-maintained copy once said "five servers",
listed six, and omitted one — then asserts each registered name has a
`server.py`, runs `--selftest` on all of them and `--demo` on those that define
one.

## How they are launched

Two different paths, and the difference matters.

**Interactive** — `.mcp.json` registers all eight as
`{"command": "python", "args": ["./mcp-servers/<name>/server.py"], "env": {"PYTHONPATH": "apps/backend/src"}}`.

**At runtime** — `apps/backend/src/cbc/modules/ops/api/toolsets.py` builds the
config per job type and passes it with `--strict-mcp-config`, so `.mcp.json` is
not consulted at all. See [`../backend/worker.md`](../backend/worker.md#tool-scope)
for which job type gets which servers. `toolsets` also injects
`MONGODB_READONLY_URI`, `MONGODB_DB` and (for `reference`) `REFERENCE_DIR`.

> **`MONGODB_READONLY_URI` is in neither `infra/docker-compose.yml` nor
> `.env.example`**, yet `bid-docs`, `catalog-docs` and `catalog` refuse to start
> without it. It works at runtime only because `WorkerLoop.loop()` derives it
> from `MONGODB_URI` via `cbc.shared.mongo.readonly_uri()` and puts it in
> `os.environ` before `toolsets.config_for` reads it. Anyone launching a server
> straight from `.mcp.json` — interactive Claude Code, or
> `python mcp-servers/main.py --selftest` — gets
> `RuntimeError: MONGODB_READONLY_URI is required`, which is why those servers'
> `_demo()` print `SKIPPED`.

## The servers

### Reading bid documents

**`bid-docs`** — `list_documents` · `get_outline` · `search_blocks` ·
`get_page_blocks`

MinerU-parsed blocks for uploaded bid PDFs, out of Mongo. `MAX_LIMIT = 50`.
This is the cheap way to find a page; `pdf-tools` is how you then read it.

**`catalog-docs`** — `list_catalogs_parsed` · `get_outline` · `search_blocks` ·
`get_page_blocks`

The same four tools over parsed vendor price books.

**`pdf-tools`** — `find_sheets` · `extract_text` · `extract_tables` ·
`get_page_image` · `get_page_size` · `search_pdf` · `parse_door_openings`

Reads PDFs off disk with PyMuPDF. Renders page images into `.cache/pdf-pages`
(or `out_dir`). Budget-guarded rather than unbounded: `MAX_HITS=200`,
`MAX_TABLE_PAGES=4`, `MAX_TEXT_PAGES=4`, `MAX_ROWS_PER_PAGE=300` — and withheld
pages are **named in the response**, never dropped silently, so a truncated read
cannot look like an empty one.

### Parts, prices and policy

**`catalog`** — `list_catalogs` · `get_catalog_overview` · `find_pages` ·
`get_page` · `get_multiplier` · `get_special_net` · `lookup_catalog_item` ·
`search_catalog_items` · `recall_match` · `is_stock_item`

The page index, `catalogItems`, and `matchLearning` for `recall_match` (Tier 0,
FR-13). Its `_demo()` asserts `"price" not in top or top.get("price") is None` —
the index returns **which page to open**, never a price. Prices are read off the
sheet.

**`reference`** — `list_reference_families` · `get_reference_document` ·
`get_margin_bands` · `get_tax_rates` · `get_finish_crosswalk` ·
`get_frame_depth` · `get_frp_constants` · `get_manual_adders` ·
`get_special_customer_margin` · `get_vendor_tier` · `get_special_net` ·
`lookup_lite_kit` · `is_stock_item` · `get_custom_other_matrix`

Serves the live `referenceData` collection, which the estimator edits at
`/settings`. **The JSON under `data/reference-library/` is seed data, not the
source of truth.**

**`calc-engine`** — `cost_from_list` · `lookup_lite_kit_list_price` ·
`calculate_line` · `apply_margin` · `compute_totals` · `validate_margin`

A pure adapter with no I/O: every formula lives in
`cbc.modules.pricing.api.calc`, so the HTTP API and the MCP tool cannot disagree
about arithmetic. Its `_demo()` pins the rounding contract —
`calculate_line(cost=74.33, margin=0.27, quantity=3)` gives `sale_ea == 101.82`
and `ext_price == 305.47`, because rounding happens once, at the extension.

**`p21-connector`** — `lookup_last_po` · `check_freshness` · `search_item`

HTTP GET only, through `client.py` (`urllib`, `P21_BASE_URL`, `P21_API_KEY`,
`P21_TIMEOUT_SECONDS`). Freshness bands come from
`cbc.modules.ops.api.freshness_rules.classify`.

With `P21_BASE_URL` unset — the normal case today — every lookup returns the
`MANUAL_ENTRY` contract: `cost_source: "MANUAL"`,
`action_required: "manual_price_entry"`. **It never invents a price.**

### Writing

**`artifact-storage`** — `save_artifact` · `propose_patch` · `get_artifact` ·
`list_versions` · `list_project_files`

The only server that writes. It is confined four ways:

- **Path allowlist.** `SAVE_ALLOW` is
  `^(extracted|priced|review)/[A-Za-z0-9._-]+\.(json|html|md)$|^quotation\.html$`,
  with explicit `..` rejection. `_project_dir` / `_resolve` re-resolve the
  target and raise `refusing to leave projects/` if it escapes.
- **Placeholder guard.** Content equal to `{file_content}`, `{content}` or
  `<file_content>` is refused, as is a `quotation.html` under 200 bytes.
- **Schema gate.** `PATH_SCHEMAS` and `prepare_artifact_text` are imported
  **without a try/except, deliberately**. They used to sit under
  `except ImportError: pass`, so a subprocess missing pydantic made the whole
  gate vanish silently.
- **Versioning.** SHA-256 content address, `atomic_write_text`, a sidecar via
  `cbc.shared.manifests.write_sidecar`, the blob in `.versions/<sha>` and an
  append-only `.versions/versions.jsonl`.

`propose_patch` applies field-level patches through
`cbc.modules.extraction.api.patching.apply_patches`. A patch that fails costs
that one field and leaves a review flag; if nothing applies, the file is left
alone rather than rewritten byte-identically.

## How read-only is enforced — and where it differs

Every read-only server asserts at **import time** that no tool name contains a
write verb, and that `set(HANDLERS) == {t["name"] for t in TOOLS}`. The asserts
are not identical, which is worth knowing before relying on one:

| Server | Import assert | Mongo connection |
|---|---|---|
| `bid-docs` | `write update insert upsert delete create set_` | **requires** `MONGODB_READONLY_URI`, raises rather than falling back |
| `catalog-docs` | same | **requires**, raises |
| `catalog` | same | **requires**, via `pageindex/reader.py` |
| `reference` | same **plus `put_`** | `prefer_ro=True` — *prefers* the read-only URI when set |
| `p21-connector` | `write update insert **post** create delete set_` | n/a — HTTP GET only |
| `pdf-tools` | **none** | n/a — filesystem only |
| `calc-engine` | none needed | n/a — no I/O |

Three things fall out of that table. `reference` only *prefers* the read-only
URI where three others refuse to start without it. `p21-connector`'s list has
`post` where the others have `upsert`, so neither list is a superset of the
other. And `pdf-tools` is the only server with no assert at all — it genuinely
has no write tools, but nothing mechanically stops one being added.

## Which server do I reach for?

`.claude/mcp/README.md` carries the plain-language version of this table for
agents. The short form:

| I want to… | Use |
|---|---|
| find which page of a bid set mentions something | `bid-docs.search_blocks` |
| actually read that page | `pdf-tools.get_page_blocks` / `extract_tables` / `get_page_image` |
| find which price-book page carries a part | `catalog.find_pages` |
| get a multiplier, special net or margin band | `reference` |
| do any arithmetic on a line | `calc-engine` (never by hand) |
| get a last-PO cost | `p21-connector.lookup_last_po` |
| save a checkpoint artifact | `artifact-storage.save_artifact` |
| correct a seeded artifact | `artifact-storage.propose_patch` |

A bare `Write` or `Edit` to a checkpoint artifact is blocked by the
`checkpoint-save-artifact` hook rule — see
[`../agents/guardrails.md`](../agents/guardrails.md).
