#!/usr/bin/env bash
# Phase 3c - Division 10 specialty take-off - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase3c_div10.sh <project_name>}" "div10-specialist" "Phase 3c - Div 10 take-off" "Only if Div 10 is in scope (scope_summary.div10_in_scope). Extract product type, manufacturer, location/drawing reference, and counts for toilet partitions, restroom accessories, washroom equipment, and hand dryers. Never invent prices. Write extracted/div10_takeoff.json."
