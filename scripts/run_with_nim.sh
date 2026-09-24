#!/bin/bash
# scripts/run_with_nim.sh
# Ensures the local LiteLLM proxy is running in Docker and configures Claude Code
# to back off properly when NVIDIA NIM rate limits (40 RPM) are hit.

set -e

# Ensure we are in the project root
cd "$(dirname "$0")/.."

# 1. Start the LiteLLM proxy via docker-compose (using the 'oss' profile)
echo "Starting LiteLLM proxy for NIM in Docker..."
docker compose -f infra/docker-compose.yml --profile oss up -d litellm

# Wait briefly for proxy to accept connections
echo "Waiting for LiteLLM proxy on port 4000..."
for i in {1..10}; do
    if curl -s http://localhost:4000/health > /dev/null; then
        echo "Proxy is ready!"
        break
    fi
    sleep 1
done

# 2. Source the Claude Code override environment
if [ -f .env.nim ]; then
    echo "Loading .env.nim overrides..."
    set -a
    source .env.nim
    set +a
else
    echo "Warning: .env.nim not found. Make sure to create it!"
fi

# 3. Run Claude Code
echo "Launching Claude Code..."
exec claude "$@"
