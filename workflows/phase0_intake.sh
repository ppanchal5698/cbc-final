#!/usr/bin/env bash
# Phase 0/1 - Intake and file setup - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase0_intake.sh <project_name>}" "intake-coordinator" "Phase 0/1 - Intake and file setup" "Create the project scaffold, move uploaded PDFs into uploads/raw/ and leave them untouched, and extract project metadata (name, number, address, state, architect, GC, initiator, bid due date, alternates) into extracted/scope_metadata.json. Capture the project STATE - sales tax depends on it."
