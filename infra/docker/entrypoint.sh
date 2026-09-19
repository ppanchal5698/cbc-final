#!/usr/bin/env bash
# Container start-up, before the API or the worker.
#
# Its whole job is declaring that /app is a trusted workspace. Claude Code
# ignores a project's permissions.allow entries until the trust dialog has been
# accepted, and an unattended container has nobody to accept it. Left unset,
# every MCP tool call is silently denied - which shows up as an extraction that
# found nothing, not as a permissions error, and costs an afternoon to diagnose.
#
# Per-job scratch cwds under data/projects/_scratch/.../workspace are trusted
# separately in cbc.worker_kit.sandbox.ensure_workspace_trusted (process mode
# and the docker sandbox entry).
#
# This runs on every start rather than at build time because the CLI rewrites
# ~/.claude.json the first time it runs, discarding a file it considers
# incomplete. Merging into whatever is there now is the version that sticks.
set -euo pipefail

python - <<'PY'
import json
from pathlib import Path

config = Path.home() / ".claude.json"
try:
    data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
except (json.JSONDecodeError, OSError):
    data = {}

project = data.setdefault("projects", {}).setdefault("/app", {})
if not project.get("hasTrustDialogAccepted"):
    project["hasTrustDialogAccepted"] = True
    config.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("[entrypoint] /app marked as a trusted workspace")
PY

# The mounted directories must be writable by this user, and a bind mount can
# silently take that away. The image chowns them to cbc (uid 1000), but a bind
# mount replaces the image's directory with the host's, ownership included - so
# a host directory owned by anyone else leaves this container unable to write to
# a path it believes it owns.
#
# Docker Desktop does not enforce bind-mount ownership, so this is invisible on
# macOS and Windows and appears only on a Linux host. Left unchecked it surfaces
# minutes later as "POST /api/projects 500" with a PermissionError buried in a
# traceback. Checking it here turns that into one line at start-up, naming the
# fix. See the ownership note in docs/operations/running.md.
# Only data/projects. `pricebooks` is deliberately asymmetric - writable on the
# api, because uploading a sheet is the human-initiated act the file-safety rule
# permits, and `:ro` on the worker, because a pipeline run must never write
# there. Asserting it here made that correct read-only mount fatal and put the
# worker in a restart loop.
for mounted in /app/data/projects /app/projects; do
  if [ -d "${mounted}" ] && [ ! -w "${mounted}" ]; then
    echo "[entrypoint] FATAL: ${mounted} is not writable by $(id -un) (uid $(id -u))." >&2
    echo "[entrypoint] It is owned by uid $(stat -c %u "${mounted}"). On the host, run:" >&2
    echo "[entrypoint]     sudo chown -R $(id -u):$(id -g) data/projects" >&2
    exit 1
  fi
done

if [ "${AUTO_BOOTSTRAP:-1}" != "0" ]; then
  # bootstrap.py already exits 0 when MongoDB is not up yet, so a failure here is
  # a real one - say so, rather than blame a Mongo that was fine.
  python /app/scripts/bootstrap.py || echo "[entrypoint] bootstrap FAILED - see the traceback above; starting anyway"
fi

exec "$@"
