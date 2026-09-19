# CI

One workflow, `.github/workflows/ci.yml`, on every pull request and on pushes to
`main`. Three jobs: `test` and `web` run in parallel, `e2e` needs both.

## `test` — the backend

Ubuntu, Python 3.12, with a `mongo:7` service container on 27017.

Two environment variables do the real work:

- **`REQUIRE_MONGO: "1"`** turns the suite's "skip when Mongo is unreachable"
  into a failure. That skip once let the whole suite go green on a codebase
  whose API could not even be imported.
- `PYTHONPATH: apps/backend/src`.

Steps, in order:

1. `pip install -r requirements.txt`, `pip install -e "./apps/backend[dev]"`,
   `pip install -e ./mcp-servers`
2. `python -m compileall -q apps/backend mcp-servers scripts` — a syntax error
   fails here, in seconds, rather than 16 minutes into pytest
3. `python -c "from cbc.app.main import create_app; print(len(create_app().openapi()['paths']), 'paths')"`
   — the app must assemble
4. `python mcp-servers/main.py --selftest` — every registered server imports,
   and every tool has a handler
5. `bash scripts/guardrails/test_no_auto_send.sh && bash scripts/guardrails/test_file_safety.sh`
6. `python -m pytest -q -rs` in `apps/backend`
7. `bash -n workflows/_phase.sh` and
   `python -m cbc.worker_kit.prompts projects/example | grep -q "NFR-1"` — the
   headless path still parses, and the rendered prompt still carries the
   no-send constraint

Note the ordering. The guardrails run **before** the test suite: a regression in
what can be sent or deleted should fail faster than a unit test, and does.

## `web` — the frontend

Ubuntu, Node 22, `working-directory: apps/web`:

```
npm ci → typecheck → lint → test → build
```

Independent of `test`, so a backend failure does not hide a frontend one.

`npm ci` must not skip the postinstall: `apps/web/scripts/copy-pdf-worker.mjs` resolves
`pdf.worker.min.mjs` through react-pdf's own require and copies it into
`public/`, so the API and worker versions cannot drift. Skip it and the PDF
viewer ships broken.

## `e2e` — Playwright against a real stack

`needs: [test, web]`. Runs the built containers and drives the real UI.

```
COMPOSE_FILE=infra/docker-compose.yml:infra/docker-compose.ci.yml
COMPOSE_PROJECT_NAME=cbc-final
```

`COMPOSE_PROJECT_NAME` is explicit because `-f infra/...` would otherwise derive
the project name from the directory, producing `infra` — and a differently-named
project does not replace the containers you think it does.

Steps:

1. `sudo chown -R 1000:1000 data/projects data/pricebooks` — the container user
2. `docker compose up -d --build web worker` with `AUTO_BOOTSTRAP=1`, naming the
   services explicitly; nginx is excluded because it crash-loops on the
   unsubstituted certificate path
3. Poll `/api/health` and `/signin`, 60 attempts at 10s
4. **Assert every service is still running** — `platform worker web mongo`. This
   check exists because the worker serves no port, so a crash-looping worker
   satisfied every HTTP probe and the suite went green against a stack with no
   worker in it
5. `npx playwright install --with-deps chromium`
6. `npx playwright test` with `PLAYWRIGHT_SKIP_WEBSERVER=1` and
   `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000`
7. On failure, upload `apps/web/test-results/` (7 days) and
   `docker compose logs --tail 200`

## What the suite actually guards

Beyond ordinary unit tests, several test groups exist to hold the architecture
rather than the behaviour. They are worth knowing before changing structure:

| Test | Fails when |
|---|---|
| `tests/architecture/test_layering.py` | a module reaches past another's `api/`, or the graph gains a cycle |
| `tests/architecture/test_composition_root.py` | `cbc.shared.config` is imported before `.env` is applied |
| `tests/architecture/test_confidence_floor.py` | `0.75` is written anywhere but `pricing/api/confidence.py` — including in the web row |
| `tests/characterization/test_contract.py` | a route exists with no pinned response |
| `tests/system/test_agent_definitions.py` | an agent names a tool it is not allowed, or the model split breaks |
| `tests/system/test_prompts.py` | a prompt names a nonexistent MCP server, or a solo run gets delegation instructions |
| `tests/system/test_headless_parity.py` | `workflows/` and the worker scope a run differently |
| `tests/system/test_no_duplicate_trees.py` | a second copy of `.claude/` appears in the tree |
| `tests/system/test_traceability_doc.py` | a doc names a path that does not exist |
| `tests/system/test_recovery.py` | job fencing, reaping or one-job-per-bid breaks — needs a real Mongo for the partial indexes |

## Running it locally

```bash
cd apps/backend && python -m pytest -q
cd apps/web && npm run typecheck && npm run lint && npm test
bash scripts/guardrails/test_no_auto_send.sh && bash scripts/guardrails/test_file_safety.sh
```

The full backend suite takes roughly 16 minutes and skips a few hundred tests
without a live Mongo. To match CI, set `REQUIRE_MONGO=1` and point
`MONGODB_URI` at a running replica set — otherwise a test that cannot reach the
database passes by skipping.
