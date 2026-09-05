# Multi-stage image for domain APIs and workers.
#
#   docker build --target api --build-arg SERVICE=intake -t cbc-intake-api .
#   docker build --target worker --build-arg SERVICE=extraction -t cbc-extraction-worker .
#   docker build --target platform-api --build-arg SERVICE=platform -t cbc-platform .
#
# SERVICE selects which services/<name> tree is copied. Workers need Claude CLI +
# MCP; slim APIs do not. Platform API keeps Claude for settings OAuth / preflight.

ARG SERVICE=platform

FROM node:22-bookworm-slim AS node

FROM docker:27-cli AS dockercli

# ── shared Python runtime (no Claude / Node / MCP) ───────────────────────────
FROM python:3.12-slim-bookworm AS python-base

ARG SERVICE=platform

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CBC_SERVICE=${SERVICE}

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git libatomic1 poppler-utils \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash cbc

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=cbc:cbc packages /app/packages
COPY --chown=cbc:cbc scripts /app/scripts
COPY --chown=cbc:cbc templates /app/templates
COPY --chown=cbc:cbc reference-library /app/reference-library
COPY --chown=cbc:cbc requirements.txt /app/requirements.txt
COPY --chown=cbc:cbc infra/docker/entrypoint.sh /app/docker/entrypoint.sh

COPY --chown=cbc:cbc services/${SERVICE}/api /app/api
COPY --chown=cbc:cbc services/${SERVICE}/ /app/service/

RUN mkdir -p /app/data/projects /app/data/pricebooks /app/.cache /home/cbc/.claude \
    && ln -sfn /app/data/projects /app/projects \
    && ln -sfn /app/data/pricebooks /app/pricebooks \
    && chown -R cbc:cbc /app /home/cbc \
    && chmod +x /app/docker/entrypoint.sh

USER cbc
ENV HOME=/home/cbc \
    PATH="/home/cbc/.local/bin:${PATH}" \
    PYTHONPATH="/app:/app/packages" \
    STORAGE_ROOT=/app/data/projects \
    PRICEBOOK_DIR=/app/data/pricebooks \
    REFERENCE_DIR=/app/reference-library \
    TEMPLATES_DIR=/app/templates

EXPOSE 8001
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ── slim domain API (intake / extraction / pricing / quoting / catalog) ───────
FROM python-base AS api

# ── platform API: Claude CLI for settings OAuth / provider preflight only ────
FROM python-base AS platform-api

USER root
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g @anthropic-ai/claude-code \
    && chown -R cbc:cbc /home/cbc
USER cbc

# ── worker: Claude CLI + Docker CLI + MCP + agent runtime ───────────────────
FROM python-base AS worker

USER root
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g @anthropic-ai/claude-code

COPY --chown=cbc:cbc mcp-servers /app/mcp-servers
COPY --chown=cbc:cbc .mcp.json /app/.mcp.json
COPY --chown=cbc:cbc .claude /app/.claude
COPY --chown=cbc:cbc agent-runtime /app/agent-runtime
# .claude/memory/process_flow.md is a pointer at docs/cbc_process_flow.md, and
# runmetrics hashes that file into every run's context fingerprint. Without it
# the agents follow a dangling reference and the hash is null.
COPY --chown=cbc:cbc docs /app/docs

RUN pip install -e ./mcp-servers \
    && chown -R cbc:cbc /app /home/cbc

USER cbc
CMD ["python", "service/worker/main.py"]
