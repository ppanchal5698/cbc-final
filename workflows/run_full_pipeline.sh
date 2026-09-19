#!/usr/bin/env bash
# CBC Estimating Copilot - full Phase 0 to 6 pipeline, headless.
#
#   bash workflows/run_full_pipeline.sh <project_name>
#
# Halts at Phase 6 with a draft quotation. Nothing is sent (NFR-1).
set -euo pipefail

PROJECT_NAME="${1:?Usage: run_full_pipeline.sh <project_name>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Same precedence as cbc.shared.paths.storage_root(), which owns this rule.
PROJECTS_ROOT="${CBC_PROJECTS_ROOT:-${STORAGE_ROOT:-${ROOT}/data/projects}}"
PROJECT_DIR="${PROJECTS_ROOT}/${PROJECT_NAME}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

cd "${ROOT}"

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Project not found: ${PROJECT_DIR}" >&2
  echo "Create it first: bash apps/backend/scripts/init_project.sh ${PROJECT_NAME} <bid-set.pdf>" >&2
  exit 1
fi

if ! compgen -G "${PROJECT_DIR}/uploads/raw/*" > /dev/null; then
  echo "No bid-set files in ${PROJECT_DIR}/uploads/raw/ - nothing to process." >&2
  exit 1
fi

echo "[$(date -Iseconds)] Pre-flight..."
PYTHONPATH="${ROOT}:${ROOT}/apps/backend/src" python apps/backend/scripts/validate_project.py --all || {
  echo "Pre-flight failed. Fix the errors above before running the pipeline." >&2
  exit 1
}

echo "[$(date -Iseconds)] Starting Phase 0-6 for ${PROJECT_NAME}"

# The orchestration prompt comes from worker_kit/prompts.py, which is what the
# Ops-Hub worker runs. This script used to restate it - a third hand-copy of the
# rules, after _phase.sh was already moved onto the shared source. Same pipeline,
# whichever way it is started.
# CBC_SOLO=1 for a provider that cannot call the Agent tool, matching the worker,
# which asks `provider.supports_subagents` rather than assuming.
PROMPT_ARGS=(--pipeline "${PROJECT_DIR}")
[[ -n "${CBC_SOLO:-}" ]] && PROMPT_ARGS=(--pipeline --solo "${PROJECT_DIR}")

PROMPT="$(PYTHONPATH="${ROOT}:${ROOT}/apps/backend/src" python -m cbc.worker_kit.prompts "${PROMPT_ARGS[@]}")" || {
  echo "Could not build the pipeline prompt from worker_kit/prompts.py" >&2
  exit 1
}

# A full run spans every phase, so it gets every server - but still through
# toolsets.py, so it is the same list the worker builds and WebSearch, WebFetch
# and NotebookEdit are removed here too. This used to spawn with no scoping at
# all, which is how a headless pipeline ended up with a wider tool surface than
# the same pipeline started from the Ops-Hub.
# See the note in _phase.sh: `mapfile < <(cmd)` cannot fail, so this guard used
# to fall open to an unrestricted run rather than closed.
SCOPE_TEXT="$(PYTHONPATH="${ROOT}:${ROOT}/apps/backend/src" python -m cbc.modules.ops.api.toolsets run_full_pipeline)" || {
  echo "Could not read the tool scope for run_full_pipeline" >&2
  exit 1
}
mapfile -t SCOPE <<< "${SCOPE_TEXT}"
if [[ "${#SCOPE[@]}" -eq 0 || -z "${SCOPE[0]}" ]]; then
  echo "Empty tool scope for run_full_pipeline - refusing to run unrestricted." >&2
  exit 1
fi

"${CLAUDE_BIN}" --print "${SCOPE[@]}" --max-turns 200 --dangerously-skip-permissions "${PROMPT}"

echo
echo "[$(date -Iseconds)] Pipeline finished."
echo "  Draft quotation: ${PROJECT_DIR}/quotation.html"
echo "  Review summary:  ${PROJECT_DIR}/review/review_summary.html"
echo "  Audit trail:     ${PROJECT_DIR}/audit_trail.jsonl"
echo
echo "Draft ready for estimator review. Nothing has been sent."
