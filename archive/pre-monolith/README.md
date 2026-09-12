# Pre-monolith archive

Trees moved here after the modular-monolith cutover (`apps/backend` +
`infra/docker-compose.yml`). They are **not** used by the live compose stack,
CI, or `pip install -e .`.

| Path | Former root role |
|---|---|
| `services/` | Per-domain FastAPI adapters + workers |
| `packages/` | Shared `cbc` kernel (`packages/cbc`) |
| `Dockerfile` | Multi-`SERVICE` image build |
| `tests/` | Root pytest / guardrail suite against the above |

## Restore (rollback)

From the repository root:

```bash
git mv archive/pre-monolith/services services
git mv archive/pre-monolith/packages packages
git mv archive/pre-monolith/Dockerfile Dockerfile
git mv archive/pre-monolith/tests tests
```

Then re-point root `pyproject.toml` / workflow `PYTHONPATH` at `packages` if you
need the pre-cutover native path. Prefer restoring from git history instead of
re-running production on this tree.

## Live path

- API + worker: `apps/backend` (`platform` + `worker` in compose)
- Web: `apps/web`
- Compose: `infra/docker-compose.yml` (or root `docker-compose.yml` include)
