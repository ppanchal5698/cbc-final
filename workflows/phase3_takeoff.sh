#!/usr/bin/env bash
# Phase 3 - Drawing take-offs - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase3_takeoff.sh <project_name>}" "takeoff-engineer" "Phase 3 - Drawing take-offs" "Locate the schedule sheets and extract every opening: door number, size, handing, finish, fire rating, door and frame type, materials, wall type and hardware-set callout. Parse the HARDWARE GROUPS block item by item. Write extracted/door_schedule.json."
