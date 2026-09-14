MinerU parses every bid PDF, tuned per machine; Claude reads the blocks, not the pages
Context
An extraction run reads bid sets page by page through pdf-tools. The last Dutch Bros run (job 6aa7fad3) used 57 turns and 1.84M cache-read tokens. Its tool results were 3.5M characters, 3.38M of them page images.

The user wants the following:

Every uploaded PDF parsed once on the GPU by MinerU.
The JSON (blocks + bbox) stored in MongoDB.
An MCP server that lets the agent query those blocks.
A bbox crop of the real PDF when the agent is unsure.
bbox evidence in the web.
This machine is a low-spec dev box; the real testing happens on a high-spec machine. So every parser setting must be tunable for low, medium and high spec, from env files and from the Settings screen.

Facts that shape it (researched and measured)
MinerU 3.4 backends (backend form field on /tasks):
Backend	VRAM needed	Accuracy score
pipeline	4 GB	86.5
hybrid-engine (effort medium or high; MinerU's default)	8 GB	95.3 / 95.4
vlm-engine	8 GB	95.3
Hybrid and VLM need mineru[core]. With vLLM installed they run fast; without it they fall back to transformers. The http-client backends are left out: they point at a remote server, which is an SSRF surface with no current need.
Dev box:
GPU: GTX 1650 Ti, 4 GB, Turing 7.5, driver 616.56, Docker Desktop with the nvidia runtime.
RAM: 8 GB in the Docker VM, 15.8 GB on the host.
Only pipeline fits, so everything else is verified on the high-spec machine.
Dutch Bros set: 65 sheets at 2592×1728 pt, all with a text layer. MinerU caps renders at 3,500 px, about 97 dpi here.
Frames: middle.json bboxes are PDF points, top-left, against its page_size. The viewer and check_extraction use the rotated display frame (shared/pdfrows.py:114); 72 of 87 pages in the first real bid set are rotated 270°.
MinerU's own MINERU_FORMULA_ENABLE / MINERU_TABLE_ENABLE env vars override request values. So they are never set on the container, and app settings use a separate PARSER_* prefix.
License: MinerU Open Source License (Apache 2.0 plus added conditions, since 3.1). CBC reviews it before commercial use.
Machine profiles
low (this dev box)	medium	high
Hardware	4–6 GB VRAM, 16 GB RAM	8–12 GB VRAM, 32 GB RAM	16 GB+ VRAM, 64 GB RAM
Runtime (Settings screen / .env)			
backend / effort	pipeline	hybrid-engine / medium	hybrid-engine / high
image analysis	off	off	on
tables / formulas	on / off	on / off	on / off
pages per window	8 (the spike sets it)	16	32
Container (infra/mineru/<profile>.env)			
base image / extras	python:3.12-slim-bookworm / pipeline	slim / core	vllm/vllm-openai:v0.21.0-cu129 / core
models	pipeline	all	all
MinerU concurrent requests / parser worker concurrency	1 / 1	1 / 1	2 / 2
extra MinerU API args	–	–	--gpu-memory-utilization 0.8
Settings: two kinds
Runtime settings. The next parse job picks them up; no restart.

Variables:
PARSER_URL (empty means parsing is off)
PARSER_PROFILE (low / medium / high)
PARSER_BACKEND, PARSER_EFFORT, PARSER_METHOD (auto / txt / ocr), PARSER_LANG
PARSER_TABLES, PARSER_FORMULAS, PARSER_IMAGE_ANALYSIS
PARSER_WINDOW_PAGES, PARSER_WINDOW_TIMEOUT_SECONDS, PARSER_WAIT_MAX_SECONDS
Where a value comes from, per field: the same rule as ops/api/provider.py build_env.
The process env. This value is locked in the UI; it is how a deployment pins a value.
/app/.env, read with cbc.shared.envfile.read().
The saved settings document (settings, _id: "parsing").
The chosen profile's preset.
Saving writes the settings document and envfile.upsert, as the Claude settings do.
Compose never interpolates PARSER_* into containers: they come from the mounted .env, so they stay editable.
Code: new ops/api/parsing_config.py holds the presets, validation and resolve(config, prefer_config=False).
It lives in ops, beside provider.py, so the intake job and the settings slices can both import it.
Validation: backend in the allowed list; effort only with hybrid; window 1–200; timeouts 60–7200 s.
Container settings. These need a rebuild or restart of the GPU service.

Files: infra/mineru/low.env, medium.env and high.env.
Variables:
MINERU_BASE_IMAGE, MINERU_EXTRAS, MINERU_MODELS, MINERU_GPU_COUNT
MINERU_API_MAX_CONCURRENT_REQUESTS, MINERU_PROCESSING_WINDOW_SIZE
MINERU_VIRTUAL_VRAM_SIZE (optional), MINERU_API_EXTRA_ARGS
PARSER_WORKER_CONCURRENCY, MINERU_SHM_SIZE
Selecting a profile: docker compose --env-file .env --env-file infra/mineru/high.env up -d --build (Compose v5.5.1 accepts repeated --env-file).
In the UI: the Settings screen shows them read-only, from MinerU GET /health (version, max_concurrent_requests, processing_window_size, queue counts). It says they change in the env file.
Design
1. GPU service mineru (new infra/mineru/Dockerfile and entrypoint.sh)
Build arguments: BASE_IMAGE and MINERU_EXTRAS.
torch is installed from the cu128 index only when the base image lacks it (the vLLM image ships its own).
Then mineru[${MINERU_EXTRAS}]>=3.4,<3.5.
Command: mineru-api --host 0.0.0.0 --port 8000 ${MINERU_API_EXTRA_ARGS} on the compose network only, with no published port.
GPU: MINERU_DEVICE_MODE=cuda, deploy.resources.reservations.devices (nvidia, count ${MINERU_GPU_COUNT:-1}), shm_size and ipc: host.
GPU only: the entrypoint exits non-zero unless torch.cuda.is_available(). There is no CPU fallback.
Models: on the first start, if the models volume lacks them, the entrypoint runs mineru-models-download -s huggingface -m ${MINERU_MODELS} into the volume mineru_models, with MINERU_TOOLS_CONFIG_JSON pointing there.
Healthcheck: GET /health.
Compose: profile gpu. Machines without a GPU leave COMPOSE_PROFILES and PARSER_URL unset, and nothing changes.
2. Parser worker (compose parser)
Why separate: the Claude worker runs WORKER_CONCURRENCY=1, so a GPU wait must not hold its slot.
Service: the worker image with WORKER_DOMAIN=parsing and WORKER_CONCURRENCY=${PARSER_WORKER_CONCURRENCY:-1}, in profile gpu, depending on mineru being healthy.
Domain wiring:
ops/features/WorkerLoop.py adds DOMAIN_JOB_TYPES["parsing"]={"parse_document"}.
WORKER_CLAIM_ALL now claims everything except parsing.
tests/architecture/test_layering.py:133 gains the domain.
3. The parse_document job (intake)
Job type: ops/domain/jobs.py JobType gains parse_document. It is not exclusive: one job per document, so a second upload never gets a 409.
Upload: intake/features/UploadDocument.py _persist enqueues parse_document {documentId} in the same transaction when PARSER_URL resolves, and sets documents.parse={state:"queued", pages}.
Handler: new intake/features/ParseDocument.py via worker.run_locally, using httpx.AsyncClient (already a dependency).
Resolve settings once per job and store them on documents.parse.settings, so it is visible which backend produced the blocks.
Health-check MinerU. If it is down, the error is retryable.
For each window: POST /tasks with backend, effort, parse_method, lang_list, formula_enable, table_enable, image_analysis, return_middle_json=true, start_page_id and end_page_id.
Poll GET /tasks/{id} every 3 s, and stop on worker.job_cancelled.
Fetch the result and save the raw JSON to projects/{slug}/uploads/processed/mineru/{docId}/p{a}-{b}.json.
Normalise and upsert the pages, then update parse.pagesDone. A retry skips windows already stored for this contentSha.
Outcome: parsed. On a permanent error, or once retries are exhausted, after_finish sets failed and records the error.
4. Normalise into documentPages (new intake/api/mineru.py)
One document per page: {projectId, documentId, contentSha, page (1-based), pageSize, blocks:[{n, type, text, bbox, lines:[{bbox,text}], html?}], verified, parser{name,version,backend,effort}, parsedAt}.
Walking blocks:
Recurse any block with nested blocks, and join the text of any block with lines/spans.
This covers the pipeline, hybrid and VLM shapes: list / code sub-types and the angle field.
Table html comes from its span. discarded_blocks are kept as discarded, because sheet numbers and title blocks land there.
Frame: if MinerU's page_size is PyMuPDF's page.rect transposed, map each bbox through page.rotation_matrix.
Verification: verified is the share of text blocks at least 50% covered by pdfrows.rows_from_words boxes (BBOX_COVERAGE). A page with no text layer gets null.
Indexes: unique (documentId, page), (projectId, page), and a text index on blocks.text. They go in intake/infrastructure/collections.py, with the name in shared/persistence/names.py.
Deleting a document (intake/features/DeleteDocument.py) also deletes its pages.
Tests use hand-built middle.json samples in all three backend shapes, because hybrid and VLM cannot run on this box.
5. Extraction waits for parsing, and never hangs on it
Waiting: ops/api/worker.py:365 defer_if_bid_busy also defers extract_bid_set, rerun_extraction and ingest_addendum while a parse_document on the bid is queued or running.
The wait lasts at most PARSER_WAIT_MAX_SECONDS (default 1800).
It is the existing 15-second requeue, with no attempt spent.
The job note reads "waiting for MinerU to parse {filename}".
Unparsed documents: these are read with pdf-tools as today, and extraction/api/validation/review.py derive_flags adds document_not_parsed (NFR-2 rule 4).
6. MCP server mcp-servers/bid-docs/ (read-only)
Pattern: follows catalog: tools.py / server.py, import-time read-only guards, _demo, serve(), and pymongo on MONGODB_READONLY_URI.
Tools:
list_documents(project)
get_outline(project, document_id): sheet number or title text and block counts per page
search_blocks(project, query, document_id?, types?, limit=20): $text search returning only the matching blocks, with bbox and page_size
get_page_blocks(project, document_id, page, types?, start=0, max_chars=20000): with a next cursor
Crops: the existing pdf-tools.get_page_image(file_path, page, region=bbox). shared/pdfpages.py page_image gains region * ~page.rotation_matrix, with a test on a page rotated 270°.
Registration: .mcp.json and toolsets.SERVERS, the _READING profile, and the read-only env tuple in config_for.
Pinned tests to update: test_toolset_registry.py:71, test_autopilot.py:59, test_workflow_cost.py:78, test_mcp_schema_parity.py, test_headless_parity.py.
7. Prompts and agents
Prompt: apps/backend/src/cbc/worker_kit/prompts.py (PREAMBLE at :86, EXTRACT at :183 and :199).
Read through bid-docs first: outline, then search, then page blocks.
Crop at a block's bbox only when a value is unclear, and never open a full page image of a parsed page.
Documents that are not parsed use pdf-tools as before.
Agents: .claude/agents/takeoff-engineer.md, spec-scope-analyst.md, frp-specialist.md and intake-coordinator.md get the bid-docs tools in their frontmatter and the same guidance.
Record bboxes stay measured by extraction/infrastructure/geometry.measure_bboxes.
8. Settings API and web
Backend (admin-only router, following ops/features/ClaudeSettings.py):
ops/features/ParsingSettings.py:
GET /api/settings/parsing returns effective values, each field's source (env / dotenv / db / profile) and locked, the presets table, and MinerU /health or its error.
PUT /api/settings/parsing validates, saves (settings document plus envfile.upsert), and records audit settings.parsing.update with the changed field names.
ops/features/TestParsingSettings.py: POST /api/settings/parsing/test.
It builds a one-page PDF with fitz (heading, paragraph, small table) and sends it to MinerU /file_parse with the on-screen values (prefer_config), with a 180 s timeout.
It returns ok, seconds, block count and MinerU version. Otherwise it names the failure: MinerU unreachable, a 400 for an unknown backend, or a missing-models error that points at the right preset env file.
intake/features/ListPageBlocks.py: GET /api/projects/{code}/documents/{id}/pages/{n}/blocks.
The contract snapshot goes from 126 to 130 routes.
Web: new components/settings/parsing-settings.tsx, mounted in app/(app)/settings/page.tsx below the Claude settings.
Profile picker: Low / Medium / High, each showing the hardware it needs; picking one fills the fields from the preset.
Fields: backend, effort (hybrid only), method, language, tables, formulas, image analysis, window pages, timeouts, and parser on/off. Env-locked fields are disabled with "Set in the server environment", using the field.locked pattern from claude-settings.tsx.
Container panel: a read-only panel from /health.
Actions: a "Test with a sample page" button, and Save.
Web: upload screen. lib/types.ts BidDocument.parse. The upload-panel.tsx state column reads "Queued for GPU", "Parsing 16 / 65 (hybrid-engine)", "Parsed" or "Not parsed — read directly".
Web: job labels. parse_document is added to lib/run-pill.ts, lib/job-error.ts, and hooks/use-pipeline-job.ts.
Web: evidence. components/extraction/sheet-viewer.tsx gets a "Show parsed blocks" toggle.
It outlines each block on the page, tables styled differently, and hovering shows the text.
Unverified pages draw nothing and say why. The selected row's highlight is unchanged.
9. Docs and config
.env.example: the runtime PARSER_* block with each profile's values in comments.
Preset files: infra/mineru/{low,medium,high}.env.
Docs: docs/architecture.md, docs/app_lifecycle.md (upload → parse → extract), docs/collections.mongodb.md (documentPages), and a "Tuning the parser" section naming both kinds of settings.
Order (one gated commit per step)
Spike on the dev box (low profile), after the downloads:
Confirm torch.cuda.get_device_name(0) in the container.
Parse Dutch Bros pages 1–8 and a copy of one page rotated 270°.
Record peak VRAM, RAM, seconds per page and the bbox frame. These set the low preset's window size and the frame code.
If pipeline runs out of memory at 4 GB, stop and report.
Backend: parsing_config (presets, resolution, validation), the settings routes and test route, job type and domain, upload enqueue, handler, normaliser, collection, blocks route, extraction wait, review flag, and the rotation fix in pdfpages. Tests use a fake MinerU client.
MCP and agents: the bid-docs server, toolsets, prompts, agents, pinned tests, and selftest.
Deployment: Dockerfile with build args, compose services, the three preset env files, and docs.
Web: settings panel, upload states, labels and the block overlay.
Live on the dev box: a Dutch Bros upload on the low profile, compared with job 6aa7fad3.
High-spec checklist for the user (written into the docs):
--env-file infra/mineru/high.env up -d --build
Settings → High → Test with a sample page
Upload the Dutch Bros set and compare runMetrics
Verification
Unit tests:
resolution order: env locked, then .env, then saved, then preset;
PUT rejects a bad backend, effort without hybrid, and out-of-range windows;
the test route against a fake MinerU for success, 400 and unreachable;
the normaliser on all three shapes and on a rotated page;
defer while parsing, then run once the parse fails or times out.
Gates:
full pytest suite with REQUIRE_MONGO=1 and the dev-DB-unchanged gate;
mcp-servers/main.py --selftest;
contract snapshot at 130 routes;
web typecheck, lint, test and build.
Live on the dev box:
Set the profile to Low in Settings and run Test with a sample page; it must report ok on pipeline.
After an upload, documents.parse.settings.backend == "pipeline" and the page count matches.
The extract note shows it waiting, then it runs. The recording shows bid-docs calls with crops only.
Against the baseline (57 turns, 1.84M cache read, 3.38M image characters), the 4 openings must still be found and bbox-verified. The overlay must line up on the sheet.
Change the window in Settings, and the next parse uses it with no restart.
Set PARSER_BACKEND in the process env, and the field shows locked.
Risks
4 GB is MinerU's floor: on an out-of-memory error, use a 4-page window and set MINERU_VIRTUAL_VRAM_SIZE=3 in low.env.
RAM: 8 GB in the Docker VM is below MinerU's 16 GB. If the parser is OOM-killed, the user raises WSL memory in %UserProfile%\.wslconfig.
Hybrid and VLM can only be proven on the high-spec machine; here they are covered by the sample-shape tests and the Test button.
Drawings are not MinerU's training domain: text is exact from the text layer, but block types may be rough. pdf-tools stays available.
License: CBC reviews it.
Downloads on this dev box (approving the plan approves exactly these)
What	Source	Size
mineru[pipeline] 3.4.x and its dependencies	PyPI	~0.5 GB
torch and torchvision cu128 wheels with NVIDIA libraries	download.pytorch.org	~3.5 GB
Pipeline models: PP-DocLayoutV2 215 MB, OCR 1.35 GB, UniMERNet 814 MB, table ONNX	Hugging Face opendatalab/PDF-Extract-Kit-1.0	~2.6 GB
That is about 6.6 GB to fetch and about 10 GB on disk; C: has 183 GB free. The medium and high profiles also fetch mineru[core], the VLM model opendatalab/MinerU2.5-Pro-2605-1.2B (2.3 GB) and, for high, the vllm/vllm-openai image. Those downloads happen only when the user starts that profile on the high-spec machine; nothing is fetched for them here.