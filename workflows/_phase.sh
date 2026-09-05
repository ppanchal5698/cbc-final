#!/usr/bin/env bash
# Shared headless invocation for the individual phase scripts.
#
#   source _phase.sh
#   run_phase <project> <agent> <phase-label> <instructions...>
#
# Each phaseN_*.sh is a thin wrapper over this. The wrappers exist because the
# architecture names them; the logic lives here once.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

# Which job type each agent's phase corresponds to, so the headless path and the
# Ops-Hub worker scope the same phase the same way. Unknown agents fail rather
# than falling back to "everything" - a silent full surface is the bug this
# mapping exists to prevent.
job_type_for() {
  case "$1" in
    intake-coordinator|spec-scope-analyst|takeoff-engineer|frp-specialist)
      echo "extract_bid_set" ;;
    product-matcher|pricing-engineer)
      echo "match_and_price" ;;
    quote-builder|quality-reviewer|delivery-agent)
      echo "build_proposal" ;;
    pricebook-ingestor)
      echo "ingest_pricebook" ;;
    *)
      echo "No job type mapped for agent '$1' - add it to job_type_for" >&2
      return 1 ;;
  esac
}

run_phase() {
  local project="${1:?project name required}"
  local agent="${2:?agent name required}"
  local label="${3:?phase label required}"
  shift 3
  local instructions="$*"

  local project_dir="projects/${project}"
  if [[ ! -d "${ROOT}/${project_dir}" ]]; then
    echo "Project not found: ${project_dir}" >&2
    echo "Create it first: bash scripts/init_project.sh ${project}" >&2
    return 1
  fi

  echo "[$(date -Iseconds)] ${label} - ${project} (agent: ${agent})"

  cd "${ROOT}"

  # The tool surface comes from cbc/core/toolsets.py, which is what the Ops-Hub
  # worker scopes each job with. This script used to pass no --mcp-config at
  # all, so a headless take-off got every server in .mcp.json plus WebSearch and
  # WebFetch - a wider surface than the same phase gets through the web app, and
  # the opposite of what an unattended pass over a customer's drawings wants.
  local job_type
  job_type="$(job_type_for "${agent}")" || return 1
  # `mapfile < <(cmd)` reports mapfile's own status, not the command's, and
  # `set -e` does not cover process substitution - so a failed toolsets call left
  # `scope` empty and the run went ahead with NO --strict-mcp-config and NO
  # --disallowed-tools, under --dangerously-skip-permissions. That is every
  # server in .mcp.json plus WebSearch and WebFetch over a customer's drawings:
  # a wider surface than the same phase gets through the Ops-Hub, which is the
  # opposite of what the lines below exist to do.
  local scope_text
  if ! scope_text="$(PYTHONPATH="${ROOT}:${ROOT}/packages" python -m cbc.core.toolsets "${job_type}")"; then
    echo "Could not read the tool scope for ${job_type}" >&2
    return 1
  fi
  local scope
  mapfile -t scope <<< "${scope_text}"
  if [[ "${#scope[@]}" -eq 0 || -z "${scope[0]}" ]]; then
    echo "Empty tool scope for ${job_type} - refusing to run unrestricted." >&2
    return 1
  fi

  # The constraints come from worker_kit/prompts.py, which is what the Ops-Hub worker
  # runs with. This script used to restate them by hand, and the copy had fallen
  # behind: no manual cut-off, no P21 rule, no audit-trail line, and no
  # requirement that an extracted record carry a bbox. Same rules, one source.
  # CBC_SOLO=1 for a provider that cannot call the Agent tool. Without it this
  # script told every provider to delegate, so a local model was instructed to
  # use a tool it does not have and spent its turns circling - the same failure
  # the worker fixed by asking the provider first.
  local prompt_args=(--job-type "${job_type}" "${project_dir}")
  local how
  if [[ -n "${CBC_SOLO:-}" ]]; then
    prompt_args=(--job-type "${job_type}" --solo "${project_dir}")
    how="Do this work yourself - the Agent tool is not available on this provider.
Read \`.claude/agents/${agent}.md\` and follow it: it holds the required output
fields, the tool order and the traps for this phase."
  else
    how="Delegate this work to the registered subagent with the Agent tool - subagent_type: ${agent}. One that cannot delegate is told to do it itself, with the same tools and the same outputs, because the alternative is what an observed local-model run actually did: read the instruction, fail to follow it, and spend its turns circling without writing anything.
This is a single-phase run. Do the delegated agent's work only. Do not launch additional subagents or touch files outside this phase's outputs."
  fi

  local prompt
  if ! prompt="$(PYTHONPATH="${ROOT}:${ROOT}/packages" python -m cbc.worker_kit.prompts "${prompt_args[@]}")"; then
    echo "Could not read the job prompt from worker_kit/prompts.py" >&2
    return 1
  fi
  "${CLAUDE_BIN}" --print "${scope[@]}" --max-turns 60 --dangerously-skip-permissions "$(cat <<EOF
You are the CBC Estimating Copilot running ${label} for project ${project}.

${how}

Working directory for all inputs and outputs: ${project_dir}/
Bid-set PDFs: ${project_dir}/uploads/raw/

${instructions}

${prompt}
EOF
)"
}
