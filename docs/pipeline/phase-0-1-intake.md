# Phase 0/1 — Intake and file setup

Turns a bid request — an emailed bid set, an RFP, or a phoned-in job — into a
project on disk with the metadata every later phase depends on.

There is no separate Phase 1. File setup folded into intake because that is how
it actually works, which is why there is no `workflows/phase1_*.sh`.

| | |
|---|---|
| **Agent** | `intake-coordinator` (haiku) |
| **Job type** | part of `extract_bid_set` |
| **Script** | `bash workflows/phase0_intake.sh <project>` |
| **Command** | `/intake` |
| **Writes** | `extracted/scope_metadata.json` — **schema-gated, blocking** |

## Inputs

An uploaded PDF, and whatever the estimator typed into the Ops-Hub intake form.

## What happens

1. **Scaffold the project.** `projects/{name}/` with `uploads/raw/`,
   `uploads/processed/`, `uploads/final/`, `extracted/`, `priced/`, `review/`.
   Backed by `cbc.shared.storage`, which resolves the root through
   `storage_root()`.
2. **Move the uploads into `uploads/raw/`.** Raw uploads are **immutable** —
   nothing ever writes back over them. Extraction output goes to
   `uploads/processed/` or `extracted/`.
3. **Scan.** `MALWARE_SCAN=clamd` routes the upload through the `clamav`
   service before it is accepted.
4. **Parse.** MinerU (the `gpu` profile, job type `parse_document`) renders the
   PDF into block batches under `uploads/processed/mineru/<documentId>/`, eight
   pages per file. Later phases read blocks from Mongo via `bid-docs` rather
   than re-parsing.
5. **Extract the project metadata** — job name, customer, general contractor,
   bid date, ship-to state, addenda. Each field records the page it came from,
   which is what the intake screen shows as per-field provenance.

## Tools

`mcp__bid-docs__list_documents` · `get_outline` · `search_blocks` ·
`get_page_blocks` — find the title block and the bid information.

`mcp__pdf-tools__extract_text` · `search_pdf` · `get_page_image` — read the
specific page once found.

`mcp__artifact-storage__save_artifact` — write the checkpoint.

## Ops-Hub wins

Where the estimator has already filled a field on the intake screen, that value
is authoritative and the agent must not overwrite it. The prompt carries this as
`ops_hub_block()` — a rendered list of the fields already set. A human who typed
the bid date knows something the title block does not.

## Ship-to state

`shipToState` matters more than it looks: it drives sales tax, and an unresolved
state means the quote shows a pending tax line rather than a number. The intake
screen warns when it is missing. `lib/tax-display.ts` on the web side never
renders a raw `UNRESOLVED` — it says "add ship-to state on Intake".

## Output

`extracted/scope_metadata.json`, validated against
`apps/backend/src/cbc/modules/extraction/api/artifacts/scope_metadata.schema.json`.
A validation failure **blocks** — `post_extraction_validate.py` exits 2 — so a
malformed metadata file cannot propagate into scoping.

## Handoff

[Phase 2 — Spec scoping](phase-2-spec-scope.md) reads the metadata and the
parsed documents to work out what CBC is actually quoting.
