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
        ca-certificates curl git libatomic1 poppler-utils tesseract-ocr \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash cbc

# -- Infisical CLI ----------------------------------------------------------
# Fetches secrets at start-up; see infra/docker/entrypoint.sh. Installed from a
# pinned release with its published sha256 verified, rather than the documented
# `curl ... | bash` installer: the one binary that reads every credential this
# system owns is a poor place to run an unpinned remote script, and a checksum
# is what makes the build reproducible and auditable (NFR-3).
#
# Bump: take the version and both digests from
# https://github.com/Infisical/infisical/releases (tag infisical-cli/vX.Y.Z,
# asset checksums.txt). tests/system/test_infisical_wiring.py asserts a digest
# is pinned for whatever version is set here.
ARG INFISICAL_CLI_VERSION=0.41.90
ARG INFISICAL_CLI_SHA256_AMD64=43e5c251ce5ba078f3751f76971a816f7b9f99c2fe4a938848af5cf5b087bf3c
ARG INFISICAL_CLI_SHA256_ARM64=993bd2217ef7f9d8e276f313a90571efda5f29308bb73d2626be178cd03013b3
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) sha="${INFISICAL_CLI_SHA256_AMD64}" ;; \
      arm64) sha="${INFISICAL_CLI_SHA256_ARM64}" ;; \
      *) echo "no pinned Infisical CLI for ${arch}" >&2; exit 1 ;; \
    esac; \
    deb="infisical_${INFISICAL_CLI_VERSION}_linux_${arch}.deb"; \
    curl -fsSL -o "/tmp/${deb}" \
      "https://github.com/Infisical/infisical/releases/download/infisical-cli%2Fv${INFISICAL_CLI_VERSION}/${deb}"; \
    echo "${sha}  /tmp/${deb}" | sha256sum -c -; \
    dpkg -i "/tmp/${deb}"; \
    rm -f "/tmp/${deb}"; \
    infisical --version

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

# `[ocr]` pulls pytesseract; the tesseract binary is installed on `base` so
# pdf-tools OCR assist works instead of always returning ocr_unavailable.
RUN pip install -e "./mcp-servers[ocr]" \
    && chown -R cbc:cbc /app /home/cbc

USER cbc
CMD ["python", "-m", "cbc.app.worker"]
