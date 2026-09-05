#!/usr/bin/env bash
# Phase 3b - FRP take-off - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase3b_frp.sh <project_name>}" "frp-specialist" "Phase 3b - FRP take-off" "Only if FRP is in scope. Capture perimeter linear feet, wall height, inside and outside corner counts and deducted openings per room. Check reference-library/frp_constants/conversion_constants.json first - while its status is PENDING, report geometry only and emit quantities as null. Write extracted/frp_takeoff.json."
