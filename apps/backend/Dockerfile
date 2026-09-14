# CBC modular monolith — compose service name remains `platform` for the API.
# Workers build the same Dockerfile with `--target worker`.

FROM node:22-bookworm-slim AS node

FROM docker:27-cli AS dockercli

# ── shared Python runtime (no Claude / Node / MCP) ───────────────────────────
FROM python:3.12-slim-bookworm AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/apps/backend/src \
    TEMPLATES_DIR=/app/templates \
    STORAGE_ROOT=/app/data/projects \
    PRICEBOOK_DIR=/app/data/pricebooks \
    REFERENCE_DIR=/app/reference-library \
    HOME=/home/cbc \
    PATH="/home/cbc/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git libatomic1 poppler-utils \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash cbc

COPY apps/backend/pyproject.toml apps/backend/README.md /app/apps/backend/
COPY apps/backend/src /app/apps/backend/src
COPY apps/backend/scripts /app/scripts
COPY requirements.txt /app/requirements.txt
COPY templates /app/templates
COPY data/reference-library /app/reference-library
COPY infra/docker/entrypoint.sh /app/docker/entrypoint.sh

RUN pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir -e /app/apps/backend \
 && mkdir -p /app/data/projects /app/data/pricebooks /app/.cache /home/cbc/.claude \
 && ln -sfn /app/data/projects /app/projects \
 && ln -sfn /app/data/pricebooks /app/pricebooks \
 && ln -sfn /app/scripts /app/apps/backend/scripts \
 && chmod +x /app/docker/entrypoint.sh \
 && chown -R cbc:cbc /app /home/cbc

USER cbc
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# ── Claude CLI: the API runs it too ─────────────────────────────────────────
# Settings' browser sign-in (`claude setup-token`), the provider test and the
# "is the CLI installed" check all run in the API process, not the worker.
FROM base AS claude

USER root
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g @anthropic-ai/claude-code \
    && chown -R cbc:cbc /home/cbc
USER cbc

FROM claude AS api
EXPOSE 8001
CMD ["uvicorn", "cbc.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]

# ── worker: + Docker CLI + MCP + agent runtime ──────────────────────────────
FROM claude AS worker

USER root
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

COPY --chown=cbc:cbc mcp-servers /app/mcp-servers
COPY --chown=cbc:cbc .mcp.json /app/.mcp.json
COPY --chown=cbc:cbc .claude /app/.claude
# The agent runtime IS .claude — one source, copied to the path the runtime expects.
RUN cp -a /app/.claude /app/agent-runtime && chown -R cbc:cbc /app/agent-runtime
COPY --chown=cbc:cbc docs /app/docs

RUN pip install -e ./mcp-servers \
    && chown -R cbc:cbc /app /home/cbc

USER cbc
CMD ["python", "-m", "cbc.app.worker"]
