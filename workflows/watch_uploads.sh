#!/usr/bin/env bash
# Watch projects/*/uploads/raw/ for new bid-set PDFs and run the pipeline.
#
#   bash workflows/watch_uploads.sh [--interval SECONDS]
#
# Uses inotifywait when available (Linux). Falls back to a portable polling loop,
# which is what runs on Windows and macOS - inotify-tools is not installed here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WATCH_DIR="${ROOT}/projects"
INTERVAL=30
[[ "${1:-}" == "--interval" ]] && INTERVAL="${2:?--interval needs seconds}"
STATE_FILE="${TMPDIR:-/tmp}/cbc_watch_seen.txt"

cd "${ROOT}"
touch "${STATE_FILE}"

launch() {
  local file="$1"
  # projects/<name>/uploads/raw/<file>
  local relative="${file#"${WATCH_DIR}/"}"
  local project="${relative%%/*}"
  [[ "${relative}" == */uploads/raw/* ]] || return 0
  [[ -d "projects/${project}/uploads/raw" ]] || return 0

  echo "[$(date -Iseconds)] New bid-set file in ${project}: $(basename "${file}")"
  bash workflows/run_full_pipeline.sh "${project}" || echo "  pipeline failed for ${project}" >&2
}

if command -v inotifywait > /dev/null 2>&1; then
  echo "Watching ${WATCH_DIR} with inotifywait. Ctrl-C to stop."
  inotifywait -m -r -e close_write --format '%w%f' "${WATCH_DIR}" |
    while read -r file; do
      [[ "${file}" == *.pdf ]] && launch "${file}"
    done
else
  echo "inotifywait not found - polling ${WATCH_DIR} every ${INTERVAL}s. Ctrl-C to stop."
  # Seed the state file so pre-existing files do not all fire on first start.
  find "${WATCH_DIR}" -path '*/uploads/raw/*' -name '*.pdf' > "${STATE_FILE}" 2>/dev/null || true
  while true; do
    find "${WATCH_DIR}" -path '*/uploads/raw/*' -name '*.pdf' 2>/dev/null |
      while read -r file; do
        grep -Fqx "${file}" "${STATE_FILE}" && continue
        echo "${file}" >> "${STATE_FILE}"
        launch "${file}"
      done
    sleep "${INTERVAL}"
  done
fi
