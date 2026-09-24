#!/usr/bin/env bash
# Phase 3 - Drawing take-offs - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase3_takeoff.sh <project_name>}" "takeoff-engineer" "Phase 3 - Drawing take-offs" "Follow the 95% ladder: door/opening schedule → Div 08 hardware schedule → Div 08 door/frame specs → floor plans. Extract every opening: door number, size, qty, handing, finish, fire rating, door and frame type, materials, wall type, hardware-set callout, structured keying when present, and alternate when marked. Parse the HARDWARE GROUPS block item by item. Never invent prices. Write extracted/line_items.json."
