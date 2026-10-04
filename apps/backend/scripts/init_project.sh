#!/usr/bin/env bash
# Scaffold a new CBC bid project directory.
#
#   bash apps/backend/scripts/init_project.sh <project_name> [source_pdf ...]
#
# Project names are lowercase with underscores: {brand}_{location}_{year}
# e.g. dutch_bros_macarthur_2026
set -euo pipefail

PROJECT_NAME="${1:?Usage: init_project.sh <project_name> [source_pdf ...]}"
shift || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

# Same precedence as cbc.shared.paths.storage_root(), which owns this rule.
# Resolved in bash rather than asked of Python: this script has to work before
# the package is installed, which is the whole point of it.
PROJECTS_ROOT="${CBC_PROJECTS_ROOT:-${STORAGE_ROOT:-${ROOT}/data/projects}}"
PROJECT_DIR="${PROJECTS_ROOT}/${PROJECT_NAME}"

if [[ ! "${PROJECT_NAME}" =~ ^[a-z0-9_]+$ ]]; then
  echo "Project name must be lowercase letters, digits and underscores: ${PROJECT_NAME}" >&2
  exit 1
fi

mkdir -p "${PROJECT_DIR}"/{uploads/{raw,processed,final},extracted,priced,review}
touch "${PROJECT_DIR}/audit_trail.jsonl"

# Copy any supplied bid-set PDFs into raw/. Raw uploads are immutable afterwards.
for pdf in "$@"; do
  if [[ -f "${pdf}" ]]; then
    cp -n "${pdf}" "${PROJECT_DIR}/uploads/raw/"
    echo "  + $(basename "${pdf}")"
  else
    echo "  ! not found: ${pdf}" >&2
  fi
done

cat <<EOF

Project scaffolded: ${PROJECT_DIR}
  uploads/raw/        bid-set PDFs as received (immutable)
  uploads/processed/  extraction artifacts
  uploads/final/      approved quotation (version controlled)
  extracted/          line_items.json, hardware_sets.json, frp_takeoff.json, scope_*.json
  priced/             line_items.json, margin_applied.json, confidence_scores.json
  review/             review_flags.json, review_summary.html, estimator_notes.md
  audit_trail.jsonl   append-only tool log

Next: bash workflows/run_full_pipeline.sh ${PROJECT_NAME}
EOF
