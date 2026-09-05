#!/usr/bin/env bash
# Phase 2 - Spec scoping - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase2_spec_scope.sh <project_name>}" "spec-scope-analyst" "Phase 2 - Spec scoping" "Identify Division 08 and Division 10 scope from the specification PDFs. Extract fire ratings and hardware-set callouts. Record out-of-scope items you found without pricing them. Write extracted/scope_summary.json."
